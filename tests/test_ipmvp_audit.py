"""
Unit tests for IPMVP Option B/C Baseline and Cryptographic Savings Ledger.
"""

import pytest
import numpy as np
from fleksa.audit.baseline import IpmvpBaselineEngine
from fleksa.audit.ledger import CryptographicSavingsLedger


def test_ipmvp_10_in_10_baseline():
    # 5 similar days with 24 hours each
    history = [[200.0 + i * 2.0 for _ in range(24)] for i in range(5)]
    baseline = IpmvpBaselineEngine.calculate_10_in_10_baseline(history)

    assert len(baseline) == 24
    # Mean of 200, 202, 204, 206, 208 = 204
    assert round(baseline[0], 1) == 204.0


def test_ipmvp_same_day_adjustment():
    baseline_curve = np.full(24, 200.0)
    # Actual load before event (e.g. event starts at hour 18, so pre-event hours 16-17) is 220 kW (+10%)
    pre_event_actual = [220.0, 220.0]

    adjusted = IpmvpBaselineEngine.apply_same_day_adjustment(
        baseline_hourly_kw=baseline_curve,
        pre_event_actual_2h_kw=pre_event_actual,
        event_start_hour=18,
    )

    # All hours should be scaled by 1.10 (220/200 = 1.10)
    assert round(adjusted[18], 1) == 220.0


def test_ipmvp_compute_event_savings():
    baseline = np.full(24, 250.0)
    actual = np.full(24, 250.0)
    # During hours 18, 19, 20, actual dropped to 100 kW (curtailed 150 kW each hour)
    for h in [18, 19, 20]:
        actual[h] = 100.0

    tariff = np.full(24, 4.0)  # 4.0 TL/kWh

    savings = IpmvpBaselineEngine.compute_event_savings(
        adjusted_baseline_kw=baseline,
        actual_meter_kw=actual,
        ptf_tariff_try_kwh=tariff,
        event_hours=[18, 19, 20],
    )

    # 150 kW * 3 hours = 450 kWh curtailed
    assert savings["net_curtailed_kwh"] == 450.0
    # 450 kWh * 4.0 TL/kWh = 1800 TL
    assert savings["net_financial_savings_try"] == 1800.0


def test_cryptographic_ledger_merkle_tree():
    ledger = CryptographicSavingsLedger()

    leaf1 = ledger.append_entry({"event": 1, "curtailed_kwh": 200.0})
    leaf2 = ledger.append_entry({"event": 2, "curtailed_kwh": 350.0})

    root = ledger.compute_merkle_root()
    assert len(root) == 64  # Valid 32-byte hex hash

    # Appending another entry must alter the root
    ledger.append_entry({"event": 3, "curtailed_kwh": 100.0})
    root2 = ledger.compute_merkle_root()
    assert root != root2


def test_empty_ledger_merkle_root():
    ledger = CryptographicSavingsLedger()
    root = ledger.compute_merkle_root()
    assert len(root) == 64


def test_ipmvp_insufficient_history_error():
    with pytest.raises(ValueError, match="At least 3 historical days required"):
        IpmvpBaselineEngine.calculate_10_in_10_baseline([[100.0] * 24])


def test_ipmvp_ashrae_14_statistical_metrics():
    # Actual load vs model baseline with mild residual noise
    actual = np.array([200.0, 205.0, 198.0, 202.0, 201.0, 199.0])
    baseline = np.array([201.0, 204.0, 199.0, 200.0, 203.0, 198.0])

    cv_rmse = IpmvpBaselineEngine.calculate_cv_rmse(actual, baseline)
    nmbe = IpmvpBaselineEngine.calculate_nmbe(actual, baseline)

    assert cv_rmse < 5.0  # Very well fit model (< 20% standard)
    assert abs(nmbe) < 2.0  # Bias well within ±5% standard

    report = IpmvpBaselineEngine.evaluate_ashrae_compliance(actual, baseline)
    assert report["is_ashrae_compliant"] is True
    assert report["compliance_grade"] == "GRADE_A_CERTIFIED"
    assert report["cv_rmse_compliant"] is True
    assert report["nmbe_compliant"] is True


def test_ipmvp_ashrae_14_edge_cases():
    # Non-compliant scenario
    actual = np.array([100.0, 150.0, 80.0, 200.0])
    baseline = np.array([250.0, 300.0, 200.0, 350.0])

    report = IpmvpBaselineEngine.evaluate_ashrae_compliance(actual, baseline)
    assert report["is_ashrae_compliant"] is False
    assert report["compliance_grade"] == "NON_COMPLIANT_MODEL"

    # Zero mean edge case
    zero_act = np.zeros(5)
    zero_base = np.zeros(5)
    assert IpmvpBaselineEngine.calculate_cv_rmse(zero_act, zero_base) == 0.0
    assert IpmvpBaselineEngine.calculate_nmbe(zero_act, zero_base) == 0.0

    # Degrees of freedom error
    with pytest.raises(ValueError, match="must exceed degrees of freedom"):
        IpmvpBaselineEngine.calculate_cv_rmse(np.array([100.0]), np.array([100.0]), p_degrees_of_freedom=1)
    with pytest.raises(ValueError, match="must exceed degrees of freedom"):
        IpmvpBaselineEngine.calculate_nmbe(np.array([100.0]), np.array([100.0]), p_degrees_of_freedom=1)


