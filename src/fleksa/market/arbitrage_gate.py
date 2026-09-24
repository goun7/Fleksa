"""
Economic Arbitrage Gate implementing Theorem 1 from Fleksa Specification §5.2.
Guarantees zero-capital-destruction invariant under battery degradation and round-trip loss.
"""

from typing import Tuple, Dict, Any
import numpy as np

from fleksa.core.constants import DEFAULT_ROUND_TRIP_EFFICIENCY
from fleksa.core.errors import OptimizationConvergenceError


class EconomicArbitrageGate:
    """
    Evaluates whether a proposed charge-discharge arbitrage pair is strictly economically profitable
    after accounting for round-trip electrical efficiency, physical LiFePO4 cell degradation,
    and stochastic risk premium.

    Theorem 1 Condition:
    lambda_dis - (lambda_ch / (eta_ch * eta_dis)) > (C_deg(DoD, T_cell) / eta_dis) + epsilon_risk
    """

    @classmethod
    def evaluate_arbitrage_viability(
        cls,
        charge_price_try_per_kwh: float,
        discharge_price_try_per_kwh: float,
        degradation_cost_try_per_kwh: float,
        round_trip_efficiency: float = DEFAULT_ROUND_TRIP_EFFICIENCY,
        risk_premium_try: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Evaluates the economic viability of an arbitrage cycle.
        Returns viability boolean, spread, required minimum spread, and net yield per kWh.
        """
        eta_rt = float(np.clip(round_trip_efficiency, 0.50, 1.0))
        eta_ch = float(np.sqrt(eta_rt))
        eta_dis = float(np.sqrt(eta_rt))

        # Effective break-even charge cost delivered
        break_even_charge_cost = charge_price_try_per_kwh / (eta_ch * eta_dis)

        # Degradation cost delivered to load/grid
        effective_deg_cost = degradation_cost_try_per_kwh / eta_dis

        # Minimum required discharge price
        min_required_discharge_price = break_even_charge_cost + effective_deg_cost + risk_premium_try

        net_margin_per_kwh = discharge_price_try_per_kwh - break_even_charge_cost - effective_deg_cost - risk_premium_try
        is_viable = net_margin_per_kwh > 0.0

        return {
            "is_viable": is_viable,
            "charge_price": charge_price_try_per_kwh,
            "discharge_price": discharge_price_try_per_kwh,
            "break_even_charge_cost": round(break_even_charge_cost, 4),
            "effective_deg_cost": round(effective_deg_cost, 4),
            "min_required_discharge_price": round(min_required_discharge_price, 4),
            "net_margin_try_per_kwh": round(net_margin_per_kwh, 4),
            "verdict": "PROFITABLE_ARBITRAGE" if is_viable else "CAPITAL_DESTRUCTION_BLOCKED",
        }
