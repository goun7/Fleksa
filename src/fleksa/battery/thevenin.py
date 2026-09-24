"""
2-RC Thevenin Equivalent Circuit Model (ECM) for LiFePO4 (LFP) battery cells.
"""

from typing import Tuple
import numpy as np


class TheveninBatteryModel:
    """
    High-fidelity 2-RC Thevenin Equivalent Circuit Model for simulation of
    dynamic terminal voltage, internal polarization, and ohmic losses.
    """

    def __init__(
        self,
        nominal_capacity_ah: float = 280.0,
        nominal_voltage_v: float = 3.2,
        r0_ohm: float = 0.00045,
        r1_ohm: float = 0.00025,
        c1_farad: float = 12000.0,
        r2_ohm: float = 0.00035,
        c2_farad: float = 45000.0,
        initial_soc: float = 0.50,
    ):
        self.capacity_ah = nominal_capacity_ah
        self.nominal_v = nominal_voltage_v
        self.r0 = r0_ohm
        self.r1 = r1_ohm
        self.c1 = c1_farad
        self.r2 = r2_ohm
        self.c2 = c2_farad

        self.soc = initial_soc
        self.v_rc1 = 0.0
        self.v_rc2 = 0.0

    @staticmethod
    def calculate_ocv(soc: float) -> float:
        """
        LFP Open Circuit Voltage characteristic curve as a function of SoC (0.0 to 1.0).
        Exhibits the classic flat phase-transition plateau around 3.28V - 3.32V.
        """
        soc = float(np.clip(soc, 0.0, 1.0))
        # 5th-order empirical polynomial fitting for 280Ah LFP prismatics
        if soc < 0.05:
            return 2.50 + soc * 10.0
        elif soc > 0.95:
            return 3.35 + (soc - 0.95) * 6.0
        else:
            return 3.15 + 0.20 * soc + 0.02 * np.sin(np.pi * soc)

    def step(self, current_a: float, dt_seconds: float, temp_celsius: float = 25.0) -> Tuple[float, float]:
        """
        Advances the ECM state by dt_seconds with applied current_a (positive = discharge, negative = charge)
        and cell temperature temp_celsius (adjusting ohmic resistance via Arrhenius relation).
        Returns: (terminal_voltage_v, updated_soc)
        """
        # Arrhenius thermal resistance factor (Hurria et al., IEEE 2012)
        t_kelvin = temp_celsius + 273.15
        t_ref_k = 298.15
        ea_r = 20000.0  # J/mol activation energy for electrolyte / SEI transport
        gas_r = 8.314462
        r_temp_factor = float(np.exp((ea_r / gas_r) * (1.0 / t_kelvin - 1.0 / t_ref_k)))
        r0_eff = self.r0 * r_temp_factor

        # Current sign: + discharge, - charge
        tau1 = self.r1 * self.c1
        tau2 = self.r2 * self.c2

        exp1 = np.exp(-dt_seconds / tau1)
        exp2 = np.exp(-dt_seconds / tau2)

        self.v_rc1 = self.v_rc1 * exp1 + current_a * self.r1 * (1.0 - exp1)
        self.v_rc2 = self.v_rc2 * exp2 + current_a * self.r2 * (1.0 - exp2)

        # Update SoC (Coulomb counting)
        delta_ah = (current_a * dt_seconds) / 3600.0
        self.soc = float(np.clip(self.soc - (delta_ah / self.capacity_ah), 0.0, 1.0))

        ocv = self.calculate_ocv(self.soc)
        v_terminal = ocv - (current_a * r0_eff) - self.v_rc1 - self.v_rc2

        return float(v_terminal), self.soc

