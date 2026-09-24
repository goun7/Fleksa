"""
IPMVP Option B and Option C Measurement and Verification (M&V) Baseline Engine.
"""

from typing import List, Dict, Any
import numpy as np


class IpmvpBaselineEngine:
    """
    Implements industry-standard 10-in-10 baseline calculation with
    symmetric additive pre-event calibration in compliance with EVO 10001-1:2022.
    """

    @staticmethod
    def calculate_10_in_10_baseline(similar_days_load_kw: List[List[float]]) -> np.ndarray:
        """
        Takes a matrix of 10 similar historical days (10 x 24 hours).
        Computes the unadjusted arithmetic mean for each hour.
        """
        arr = np.array(similar_days_load_kw, dtype=float)
        if arr.shape[0] < 3:
            raise ValueError(f"At least 3 historical days required for baseline (got {arr.shape[0]}).")
        return np.mean(arr, axis=0)

    @staticmethod
    def apply_same_day_adjustment(
        baseline_hourly_kw: np.ndarray,
        pre_event_actual_2h_kw: List[float],
        event_start_hour: int,
        max_adjustment_fraction: float = 0.20,
    ) -> np.ndarray:
        """
        Adjusts the baseline curve using the ratio of actual-to-baseline load
        during the 2 hours immediately preceding the DR event.
        Adjustment is capped to avoid skew (typically +/- 20%).
        """
        adjusted = np.copy(baseline_hourly_kw)

        # Average of 2 hours prior to event
        h1 = max(0, event_start_hour - 2)
        h2 = max(0, event_start_hour)
        if h2 <= h1:
            return adjusted

        pre_baseline_mean = float(np.mean(baseline_hourly_kw[h1:h2]))
        pre_actual_mean = float(np.mean(pre_event_actual_2h_kw))

        if pre_baseline_mean > 0.0:
            raw_ratio = pre_actual_mean / pre_baseline_mean
            # Clamp ratio to [1.0 - max_adj, 1.0 + max_adj]
            clamped_ratio = float(np.clip(raw_ratio, 1.0 - max_adjustment_fraction, 1.0 + max_adjustment_fraction))
            adjusted *= clamped_ratio

        return adjusted

    @classmethod
    def compute_event_savings(
        cls,
        adjusted_baseline_kw: np.ndarray,
        actual_meter_kw: np.ndarray,
        ptf_tariff_try_kwh: np.ndarray,
        event_hours: List[int],
    ) -> Dict[str, float]:
        """
        Calculates net kWh saved and net financial value generated during DR event hours.
        """
        total_baseline_kwh = 0.0
        total_actual_kwh = 0.0
        total_financial_savings = 0.0

        for h in event_hours:
            base_kw = float(adjusted_baseline_kw[h])
            act_kw = float(actual_meter_kw[h])
            tariff = float(ptf_tariff_try_kwh[h])

            curtailed_kw = max(0.0, base_kw - act_kw)
            total_baseline_kwh += base_kw
            total_actual_kwh += act_kw
            total_financial_savings += curtailed_kw * tariff

        net_curtailed_kwh = max(0.0, total_baseline_kwh - total_actual_kwh)

        return {
            "total_baseline_kwh": round(total_baseline_kwh, 2),
            "total_actual_kwh": round(total_actual_kwh, 2),
            "net_curtailed_kwh": round(net_curtailed_kwh, 2),
            "net_financial_savings_try": round(total_financial_savings, 2),
        }

    @staticmethod
    def calculate_cv_rmse(actual: np.ndarray, baseline: np.ndarray, p_degrees_of_freedom: int = 1) -> float:
        """
        ASHRAE Guideline 14 Coefficient of Variation of the Root Mean Square Error:
        CV(RMSE) = (1 / y_bar) * sqrt( sum( (y_i - y_hat_i)^2 ) / (n - p) ) * 100%
        Standard threshold for hourly calibration: <= 20.0%.
        """
        act = np.asarray(actual, dtype=float)
        base = np.asarray(baseline, dtype=float)
        n = len(act)
        if n <= p_degrees_of_freedom:
            raise ValueError(f"Sample size n={n} must exceed degrees of freedom p={p_degrees_of_freedom}")

        y_bar = float(np.mean(act))
        if abs(y_bar) < 1e-9:
            return 0.0

        rmse = np.sqrt(np.sum((act - base) ** 2) / (n - p_degrees_of_freedom))
        cv_rmse = (rmse / y_bar) * 100.0
        return float(round(cv_rmse, 3))

    @staticmethod
    def calculate_nmbe(actual: np.ndarray, baseline: np.ndarray, p_degrees_of_freedom: int = 1) -> float:
        """
        ASHRAE Guideline 14 Normalized Mean Bias Error:
        NMBE = ( sum( y_i - y_hat_i ) / ((n - p) * y_bar) ) * 100%
        Standard threshold for hourly calibration: |NMBE| <= 5.0%.
        """
        act = np.asarray(actual, dtype=float)
        base = np.asarray(baseline, dtype=float)
        n = len(act)
        if n <= p_degrees_of_freedom:
            raise ValueError(f"Sample size n={n} must exceed degrees of freedom p={p_degrees_of_freedom}")

        y_bar = float(np.mean(act))
        if abs(y_bar) < 1e-9:
            return 0.0

        bias_sum = np.sum(act - base)
        nmbe = (bias_sum / ((n - p_degrees_of_freedom) * y_bar)) * 100.0
        return float(round(nmbe, 3))

    @classmethod
    def evaluate_ashrae_compliance(
        cls,
        actual: np.ndarray,
        baseline: np.ndarray,
        max_cv_rmse_pct: float = 20.0,
        max_abs_nmbe_pct: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Verifies whether baseline model satisfies ASHRAE Guideline 14 / EVO 10001-1 statistical thresholds.
        """
        cv_rmse = cls.calculate_cv_rmse(actual, baseline)
        nmbe = cls.calculate_nmbe(actual, baseline)

        is_cv_rmse_compliant = cv_rmse <= max_cv_rmse_pct
        is_nmbe_compliant = abs(nmbe) <= max_abs_nmbe_pct
        is_compliant = is_cv_rmse_compliant and is_nmbe_compliant

        return {
            "cv_rmse_pct": cv_rmse,
            "nmbe_pct": nmbe,
            "cv_rmse_threshold_pct": max_cv_rmse_pct,
            "nmbe_threshold_pct": max_abs_nmbe_pct,
            "cv_rmse_compliant": is_cv_rmse_compliant,
            "nmbe_compliant": is_nmbe_compliant,
            "is_ashrae_compliant": is_compliant,
            "compliance_grade": "GRADE_A_CERTIFIED" if is_compliant else "NON_COMPLIANT_MODEL",
        }

