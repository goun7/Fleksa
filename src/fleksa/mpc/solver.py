"""
Receding Horizon Model Predictive Control (MPC) Solver for Fleksa.
Uses scipy.optimize.milp with native C++ HiGHS branch-and-cut solver.
"""

from typing import Dict, Any, List, Optional
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

from fleksa.core.constants import (
    DEFAULT_ROUND_TRIP_EFFICIENCY,
    MIN_SAFE_SOC,
    MAX_SAFE_SOC,
)
from fleksa.core.types import (
    FacilityState,
    MarketDataHorizon,
    OptimizationResult,
    BessMode,
)
from fleksa.core.errors import OptimizationConvergenceError


class FleksaMPCSolver:
    """
    High-performance, deterministic MILP solver for 24-hour BESS arbitrage,
    power capping, and industrial load management.
    """

    def __init__(
        self,
        state: FacilityState,
        horizon_data: MarketDataHorizon,
        delta_t_hours: float = 1.0,
        gpu_max_kw: float = 200.0,
        degradation_cost_per_kwh: float = 0.35,
        min_gpu_cap: float = 0.65,
        water_cost_per_kwh: float = 0.0,
    ):
        self.state = state
        self.data = horizon_data
        self.H = horizon_data.hours
        self.dt = delta_t_hours
        self.gpu_max_kw = gpu_max_kw
        self.c_deg = degradation_cost_per_kwh
        self.min_gpu_cap = min_gpu_cap
        self.water_cost_per_kwh = water_cost_per_kwh

        # Efficiencies
        eta_rt = state.eta_rt or DEFAULT_ROUND_TRIP_EFFICIENCY
        self.eta_ch = float(np.sqrt(eta_rt))
        self.eta_dis = float(np.sqrt(eta_rt))

    def solve(self) -> OptimizationResult:
        H = self.H
        num_vars_per_step = 7
        total_vars = H * num_vars_per_step

        # Objective vector c: minimize c^T * x
        c = np.zeros(total_vars)
        integrality = np.zeros(total_vars, dtype=int)

        lower_bounds = np.zeros(total_vars)
        upper_bounds = np.zeros(total_vars)

        min_soc = self.state.bess_capacity_kwh * self.state.min_soc_pct
        max_soc = self.state.bess_capacity_kwh * self.state.max_soc_pct

        for t in range(H):
            base_idx = t * num_vars_per_step

            # 0: P_grid (Electricity tariff + water cooling footprint cost)
            c[base_idx + 0] = self.dt * (float(self.data.ptf_try_kwh[t]) + self.water_cost_per_kwh)
            lower_bounds[base_idx + 0] = 0.0
            upper_bounds[base_idx + 0] = 1e6  # Transformer capacity bound

            # 1: P_ch
            c[base_idx + 1] = 0.0
            lower_bounds[base_idx + 1] = 0.0
            upper_bounds[base_idx + 1] = self.state.bess_max_kw

            # 2: P_dis
            c[base_idx + 2] = self.dt * self.c_deg
            lower_bounds[base_idx + 2] = 0.0
            upper_bounds[base_idx + 2] = self.state.bess_max_kw

            # 3: u_ch (binary)
            integrality[base_idx + 3] = 1
            lower_bounds[base_idx + 3] = 0
            upper_bounds[base_idx + 3] = 1

            # 4: u_dis (binary)
            integrality[base_idx + 4] = 1
            lower_bounds[base_idx + 4] = 0
            upper_bounds[base_idx + 4] = 1

            # 5: SoC_{t+1}
            lower_bounds[base_idx + 5] = min_soc
            upper_bounds[base_idx + 5] = max_soc

            # 6: kappa_gpu (GPU power cap)
            # Small penalty for throttling GPU (to prefer 1.0 when electricity is cheap)
            c[base_idx + 6] = -1.0 * (float(self.data.ptf_try_kwh[t]) * 0.05)
            lower_bounds[base_idx + 6] = self.min_gpu_cap
            upper_bounds[base_idx + 6] = 1.0

        # Constraints
        # Total constraints = H (power balance) + H (ch limit) + H (dis limit) + H (mutex) + H (SoC dynamics)
        num_constraints = 5 * H
        A = np.zeros((num_constraints, total_vars))
        lhs = np.zeros(num_constraints)
        rhs = np.zeros(num_constraints)

        row = 0

        # 1. Power balance constraints: P_grid - P_ch + P_dis - gpu_max * kappa = P_base - P_pv
        for t in range(H):
            base_idx = t * num_vars_per_step
            A[row, base_idx + 0] = 1.0   # P_grid
            A[row, base_idx + 1] = -1.0  # -P_ch
            A[row, base_idx + 2] = 1.0   # +P_dis
            A[row, base_idx + 6] = -self.gpu_max_kw  # -gpu_max * kappa

            target_val = float(self.data.base_load_kw[t]) - float(self.data.pv_gen_kw[t])
            lhs[row] = target_val
            rhs[row] = target_val
            row += 1

        # 2. Charging exclusion: P_ch - bess_max * u_ch <= 0
        for t in range(H):
            base_idx = t * num_vars_per_step
            A[row, base_idx + 1] = 1.0
            A[row, base_idx + 3] = -self.state.bess_max_kw
            lhs[row] = -np.inf
            rhs[row] = 0.0
            row += 1

        # 3. Discharging exclusion: P_dis - bess_max * u_dis <= 0
        for t in range(H):
            base_idx = t * num_vars_per_step
            A[row, base_idx + 2] = 1.0
            A[row, base_idx + 4] = -self.state.bess_max_kw
            lhs[row] = -np.inf
            rhs[row] = 0.0
            row += 1

        # 4. Mutex: u_ch + u_dis <= 1
        for t in range(H):
            base_idx = t * num_vars_per_step
            A[row, base_idx + 3] = 1.0
            A[row, base_idx + 4] = 1.0
            lhs[row] = -np.inf
            rhs[row] = 1.0
            row += 1

        # 5. SoC Dynamics: SoC_{t+1} - SoC_t - P_ch * eta_ch * dt + P_dis / eta_dis * dt = 0
        for t in range(H):
            base_idx = t * num_vars_per_step
            A[row, base_idx + 5] = 1.0  # SoC_{t+1}
            A[row, base_idx + 1] = -self.eta_ch * self.dt
            A[row, base_idx + 2] = (1.0 / self.eta_dis) * self.dt

            if t == 0:
                lhs[row] = self.state.bess_soc_kwh
                rhs[row] = self.state.bess_soc_kwh
            else:
                prev_soc_idx = (t - 1) * num_vars_per_step + 5
                A[row, prev_soc_idx] = -1.0
                lhs[row] = 0.0
                rhs[row] = 0.0
            row += 1

        constraints = LinearConstraint(A, lhs, rhs)
        bounds = Bounds(lower_bounds, upper_bounds)

        # Solve with SciPy HiGHS
        res = milp(c=c, integrality=integrality, constraints=constraints, bounds=bounds)

        if not res.success or res.status != 0:
            raise OptimizationConvergenceError(
                f"HiGHS MILP failed to find an optimal solution. Status: {res.status}, Message: {res.message}"
            )

        sol = res.x
        p_grid_sol = [float(sol[t * num_vars_per_step + 0]) for t in range(H)]
        p_ch_sol = [float(sol[t * num_vars_per_step + 1]) for t in range(H)]
        p_dis_sol = [float(sol[t * num_vars_per_step + 2]) for t in range(H)]
        soc_sol = [self.state.bess_soc_kwh] + [float(sol[t * num_vars_per_step + 5]) for t in range(H)]
        gpu_cap_sol = [float(sol[t * num_vars_per_step + 6]) for t in range(H)]

        # Calculate baseline unoptimized cost (no BESS, 100% GPU cap)
        baseline_cost = float(
            sum(
                self.dt
                * float(self.data.ptf_try_kwh[t])
                * (float(self.data.base_load_kw[t]) + self.gpu_max_kw - float(self.data.pv_gen_kw[t]))
                for t in range(H)
            )
        )
        optimized_cost = float(res.fun)
        expected_savings = max(0.0, baseline_cost - optimized_cost)

        return OptimizationResult(
            status="OPTIMAL",
            projected_cost_try=optimized_cost,
            p_ch_kw=p_ch_sol,
            p_dis_kw=p_dis_sol,
            p_grid_kw=p_grid_sol,
            gpu_power_cap_pct=gpu_cap_sol,
            soc_trajectory_kwh=soc_sol,
            expected_savings_try=expected_savings,
            metadata={
                "solver": "HiGHS_MILP",
                "baseline_cost_try": baseline_cost,
                "first_hour_mode": BessMode.CHARGE.value
                if p_ch_sol[0] > 1.0
                else (BessMode.DISCHARGE.value if p_dis_sol[0] > 1.0 else BessMode.HOLD.value),
            },
        )
