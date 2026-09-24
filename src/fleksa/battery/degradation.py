"""
Physics-informed semi-empirical battery degradation and thermal model for Fleksa.
Based on Wang et al. (Journal of Power Sources) and NREL empirical parameters.
"""

from typing import Tuple
import numpy as np

from fleksa.core.constants import (
    GAS_CONSTANT_R,
    LFP_ACTIVATION_ENERGY_EA,
    WANG_ALPHA_C_RATE,
    WANG_B_BASE,
    WANG_TIME_EXPONENT_Z,
    KELVIN_OFFSET,
    MAX_CELL_TEMP_CELSIUS,
    ECKER_CALENDAR_EA,
    ECKER_BETA_SOC,
    ECKER_K_CAL,
)
from fleksa.core.errors import SafetyGuardViolationError


class BatteryDegradationEngine:
    """
    Computes capacity loss, State of Health (SoH) fade, thermal evolution,
    and marginal cycle cost for LFP energy storage systems.
    """

    def __init__(
        self,
        bess_replacement_capex_try_per_kwh: float = 4500.0,
        thermal_mass_j_per_k: float = 25000.0,
        cooling_h_a_w_per_k: float = 120.0,
    ):
        self.capex_per_kwh = bess_replacement_capex_try_per_kwh
        self.thermal_mass = thermal_mass_j_per_k
        self.cooling_h_a = cooling_h_a_w_per_k
        self.accumulated_ah: float = 0.0

    def compute_capacity_loss_pct(
        self,
        c_rate: float,
        temp_celsius: float,
        cumulative_ah: float,
    ) -> float:
        """
        Wang et al. semi-empirical formulation:
        Q_loss = (B_base + alpha * c_rate) * exp(-E_a / (R * T_kelvin)) * (Ah)^z
        Returns percentage capacity loss (0.0 to 100.0).
        """
        temp_k = temp_celsius + KELVIN_OFFSET
        b_coeff = WANG_B_BASE + WANG_ALPHA_C_RATE * abs(c_rate)

        arrhenius = np.exp(-LFP_ACTIVATION_ENERGY_EA / (GAS_CONSTANT_R * temp_k))
        q_loss = b_coeff * arrhenius * (max(0.0, cumulative_ah) ** WANG_TIME_EXPONENT_Z) * 100.0
        return float(q_loss)

    def compute_calendar_loss_pct(
        self,
        temp_celsius: float,
        average_soc: float,
        days: float,
    ) -> float:
        """
        Ecker et al. / Schmalstieg LFP calendar aging model:
        Q_cal = k_cal * exp(-E_a,cal / (R * T_kelvin)) * exp(beta_soc * SoC) * (days)^0.5 * 100%
        """
        temp_k = temp_celsius + KELVIN_OFFSET
        arrhenius = np.exp(-ECKER_CALENDAR_EA / (GAS_CONSTANT_R * temp_k))
        soc_factor = np.exp(ECKER_BETA_SOC * float(np.clip(average_soc, 0.0, 1.0)))
        time_factor = np.sqrt(max(0.0, days))
        q_cal = ECKER_K_CAL * arrhenius * soc_factor * time_factor * 100.0
        return float(q_cal)

    def compute_total_capacity_loss_pct(
        self,
        c_rate: float,
        temp_celsius: float,
        cumulative_ah: float,
        average_soc: float = 0.50,
        days: float = 1.0,
    ) -> float:
        """
        Combined electro-chemical cycle loss + calendar loss (Wang + Ecker synthesis).
        """
        cycle_loss = self.compute_capacity_loss_pct(c_rate, temp_celsius, cumulative_ah)
        calendar_loss = self.compute_calendar_loss_pct(temp_celsius, average_soc, days)
        return float(cycle_loss + calendar_loss)

    def marginal_cost_per_kwh(
        self,
        depth_of_discharge_pct: float,
        cell_temp_celsius: float = 25.0,
    ) -> float:
        """
        Computes the true marginal degradation cost (TL/kWh) for discharging.
        Deep discharge (>80%) and high temperatures dramatically increase marginal cost.
        """
        dod = float(np.clip(depth_of_discharge_pct, 0.0, 100.0))

        # Base piecewise cost
        if dod <= 20.0:
            base_c = 0.15
        elif dod <= 50.0:
            base_c = 0.32
        elif dod <= 80.0:
            base_c = 0.68
        else:
            base_c = 1.35

        # Temperature thermal penalty factor: aging accelerates above 30°C
        temp_penalty = 1.0
        if cell_temp_celsius > 30.0:
            temp_penalty += (cell_temp_celsius - 30.0) * 0.04

        return float(base_c * temp_penalty)

    def thermal_step(
        self,
        current_temp_c: float,
        ambient_temp_c: float,
        power_loss_watts: float,
        dt_seconds: float,
    ) -> float:
        """
        Lumped-parameter thermal evolution:
        m * c_p * dT/dt = P_loss - h * A * (T_cell - T_amb)
        """
        heat_transfer = self.cooling_h_a * (current_temp_c - ambient_temp_c)
        net_heat_flow_w = power_loss_watts - heat_transfer

        delta_t = (net_heat_flow_w * dt_seconds) / self.thermal_mass
        new_temp = current_temp_c + delta_t

        if new_temp > MAX_CELL_TEMP_CELSIUS:
            raise SafetyGuardViolationError(
                f"Thermal cutoff breached: Cell temperature {new_temp:.1f}°C exceeds safe threshold ({MAX_CELL_TEMP_CELSIUS}°C)."
            )

        return float(new_temp)
