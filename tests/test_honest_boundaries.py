"""
Honest-boundary expansion tests for Fleksa (84 -> 104+ target).

These deliberately attack the edges the existing suite left open:
  * degradation model piecewise branches and thermal safety cutoff
  * price canary rejection paths and boundary values
  * market feed parsing fallbacks
  * Thevenin OCV piecewise segments
  * arbitrage gate break-even algebra
"""

import pytest
import numpy as np

from fleksa.battery.degradation import BatteryDegradationEngine
from fleksa.battery.thevenin import TheveninBatteryModel
from fleksa.core.errors import SafetyGuardViolationError, ByzantinePriceFeedError
from fleksa.market.canary import TriangulationCanary
from fleksa.market.feeds import EpiasDataParser, MarketPricePoint
from fleksa.market.arbitrage_gate import EconomicArbitrageGate
from fleksa.audit.baseline import IpmvpBaselineEngine
from fleksa.audit.ledger import CryptographicSavingsLedger


# --------------------------------------------------------------------------
# Degradation model — every piecewise branch
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "dod,expected_base",
    [(5.0, 0.15), (20.0, 0.15), (21.0, 0.32), (50.0, 0.32),
     (51.0, 0.68), (80.0, 0.68), (81.0, 1.35), (100.0, 1.35)],
)
def test_marginal_cost_piecewise_branches(dod, expected_base):
    eng = BatteryDegradationEngine()
    cost = eng.marginal_cost_per_kwh(dod, cell_temp_celsius=25.0)
    assert cost == pytest.approx(expected_base)


def test_marginal_cost_thermal_penalty_only_above_30c():
    eng = BatteryDegradationEngine()
    cold = eng.marginal_cost_per_kwh(50.0, cell_temp_celsius=25.0)
    warm = eng.marginal_cost_per_kwh(50.0, cell_temp_celsius=35.0)
    assert cold == pytest.approx(0.32)
    # +5 C over 30 C => penalty 1 + 5*0.04 = 1.20
    assert warm == pytest.approx(0.32 * 1.20)


def test_marginal_cost_clamps_dod_out_of_range():
    eng = BatteryDegradationEngine()
    assert eng.marginal_cost_per_kwh(-50.0) == pytest.approx(0.15)
    assert eng.marginal_cost_per_kwh(500.0) == pytest.approx(1.35)


def test_capacity_loss_grows_with_cumulative_ah():
    eng = BatteryDegradationEngine()
    small = eng.compute_capacity_loss_pct(1.0, 25.0, 100.0)
    large = eng.compute_capacity_loss_pct(1.0, 25.0, 10_000.0)
    assert large > small > 0.0


def test_capacity_loss_accelerates_with_c_rate():
    eng = BatteryDegradationEngine()
    low = eng.compute_capacity_loss_pct(0.5, 25.0, 5000.0)
    high = eng.compute_capacity_loss_pct(5.0, 25.0, 5000.0)
    assert high > low


def test_capacity_loss_increases_with_temperature():
    eng = BatteryDegradationEngine()
    cold = eng.compute_capacity_loss_pct(1.0, 10.0, 5000.0)
    hot = eng.compute_capacity_loss_pct(1.0, 45.0, 5000.0)
    assert hot > cold


def test_calendar_loss_scales_with_sqrt_days():
    eng = BatteryDegradationEngine()
    d1 = eng.compute_calendar_loss_pct(25.0, 0.5, 100.0)
    d4 = eng.compute_calendar_loss_pct(25.0, 0.5, 400.0)
    # sqrt(4x) = 2x on the calendar term
    assert d4 == pytest.approx(2.0 * d1, rel=1e-6)


def test_calendar_loss_soc_clipped_and_monotonic():
    eng = BatteryDegradationEngine()
    below = eng.compute_calendar_loss_pct(25.0, -1.0, 10.0)
    at0 = eng.compute_calendar_loss_pct(25.0, 0.0, 10.0)
    at1 = eng.compute_calendar_loss_pct(25.0, 2.0, 10.0)
    above = eng.compute_calendar_loss_pct(25.0, 5.0, 10.0)
    assert below == at0           # clipped to 0
    assert above == at1           # clipped to 1
    assert at1 > at0


def test_total_loss_is_sum_of_cycle_and_calendar():
    eng = BatteryDegradationEngine()
    cycle = eng.compute_capacity_loss_pct(1.0, 30.0, 1000.0)
    cal = eng.compute_calendar_loss_pct(30.0, 0.5, 10.0)
    total = eng.compute_total_capacity_loss_pct(1.0, 30.0, 1000.0, 0.5, 10.0)
    assert total == pytest.approx(cycle + cal)


def test_thermal_step_converges_to_ambient():
    """With zero power loss the cell must relax toward ambient temperature."""
    eng = BatteryDegradationEngine()
    t = 40.0
    for _ in range(500):
        t = eng.thermal_step(t, ambient_temp_c=25.0, power_loss_watts=0.0, dt_seconds=60.0)
    assert t == pytest.approx(25.0, abs=1e-3)


def test_thermal_step_raises_on_safety_cutoff():
    eng = BatteryDegradationEngine(thermal_mass_j_per_k=1.0, cooling_h_a_w_per_k=0.0)
    with pytest.raises(SafetyGuardViolationError, match="Thermal cutoff"):
        eng.thermal_step(40.0, ambient_temp_c=25.0, power_loss_watts=1e6, dt_seconds=1.0)


# --------------------------------------------------------------------------
# Price canary — rejection and boundary behaviour
# --------------------------------------------------------------------------
def test_canary_rejects_implausibly_high_price():
    canary = TriangulationCanary()
    with pytest.raises(ByzantinePriceFeedError, match="Implausible"):
        canary.verify_price_quorum(1_000_000.0, 2400.0, 2380.0)


def test_canary_rejects_implausibly_negative_price():
    canary = TriangulationCanary()
    with pytest.raises(ByzantinePriceFeedError, match="Implausible"):
        canary.verify_price_quorum(-1000.0, 2400.0, 2380.0)


def test_canary_accepts_one_byzantine_feed():
    """2-of-3: one divergent (but plausible) feed must not break consensus."""
    canary = TriangulationCanary(max_allowed_divergence_pct=35.0)
    price = canary.verify_price_quorum(2400.0, 2450.0, 4900.0)
    # The two conforming feeds average out
    assert 2300.0 < price < 2500.0


def test_canary_rejects_full_byzantine_divergence():
    canary = TriangulationCanary(max_allowed_divergence_pct=10.0)
    with pytest.raises(ByzantinePriceFeedError, match="consensus failed"):
        canary.verify_price_quorum(1000.0, 5000.0, 9000.0)


def test_canary_median_equals_mean_for_symmetric_feeds():
    canary = TriangulationCanary()
    price = canary.verify_price_quorum(2000.0, 3000.0, 4000.0)
    assert price == pytest.approx(3000.0)


def test_canary_zero_median_guard_uses_max_100():
    """When the median is ~0 the divergence denominator must not divide by ~0."""
    canary = TriangulationCanary(max_allowed_divergence_pct=200.0)
    price = canary.verify_price_quorum(0.0, 0.0, 0.0)
    assert price == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Market feed parsing
# --------------------------------------------------------------------------
def test_feeds_parse_ptf_and_smf():
    pts = EpiasDataParser.parse_hourly_prices([
        {"date": "2026-09-29T10:00:00Z", "price": 2500.0, "smf": 2600.0,
         "direction": "ENERGY_DEFICIT"},
    ])
    assert len(pts) == 1
    assert pts[0].ptf_try_kwh == pytest.approx(2.5)
    assert pts[0].smf_try_kwh == pytest.approx(2.6)
    assert pts[0].system_direction.value == "ENERGY_DEFICIT"


def test_feeds_smf_defaults_to_ptf_when_missing():
    pts = EpiasDataParser.parse_hourly_prices([
        {"timestamp": "2026-09-29T11:00:00+03:00", "ptf": 2400.0},
    ])
    assert pts[0].smf_try_mwh == pytest.approx(2400.0)


def test_feeds_unknown_direction_falls_back_to_balanced():
    pts = EpiasDataParser.parse_hourly_prices([
        {"date": "2026-09-29T10:00:00", "price": 100.0, "direction": "NUCLEAR_SURPLUS"},
    ])
    assert pts[0].system_direction.value == "BALANCED"


def test_feeds_empty_input_returns_empty():
    assert EpiasDataParser.parse_hourly_prices([]) == []


def test_price_point_kwh_conversion_roundtrip():
    """kWh accessors must be exactly MWh/1000 both directions."""
    from datetime import datetime
    from fleksa.core.types import SystemDirection
    pt = MarketPricePoint(
        timestamp=datetime(2026, 9, 29, 10),
        ptf_try_mwh=2500.0,
        smf_try_mwh=2600.0,
        system_direction=SystemDirection.BALANCED,
    )
    assert pt.ptf_try_kwh == pytest.approx(2.5)
    assert pt.smf_try_kwh == pytest.approx(2.6)


# --------------------------------------------------------------------------
# Arbitrage gate algebra
# --------------------------------------------------------------------------
def test_arbitrage_gate_unviable_when_spread_below_break_even():
    res = EconomicArbitrageGate.evaluate_arbitrage_viability(
        charge_price_try_per_kwh=3.0,
        discharge_price_try_per_kwh=3.1,
        degradation_cost_try_per_kwh=0.35,
        round_trip_efficiency=0.88,
    )
    assert not res["is_viable"]
    assert res["verdict"] != "VIABLE"


def test_arbitrage_gate_viable_on_healthy_spread():
    res = EconomicArbitrageGate.evaluate_arbitrage_viability(
        charge_price_try_per_kwh=1.0,
        discharge_price_try_per_kwh=5.0,
        degradation_cost_try_per_kwh=0.35,
        round_trip_efficiency=0.88,
    )
    assert res["is_viable"]
    assert res["net_margin_try_per_kwh"] > 0.0


def test_arbitrage_gate_higher_efficiency_lowers_break_even():
    """Better round-trip efficiency means less energy bought per kWh delivered,
    so the break-even charge cost (per kWh delivered) must fall."""
    lo = EconomicArbitrageGate.evaluate_arbitrage_viability(
        1.0, 5.0, 0.35, 0.50)
    hi = EconomicArbitrageGate.evaluate_arbitrage_viability(
        1.0, 5.0, 0.35, 0.95)
    assert hi["break_even_charge_cost"] < lo["break_even_charge_cost"]
    # Sanity of the algebra: break_even = charge / eta_rt
    assert lo["break_even_charge_cost"] == pytest.approx(2.0, rel=1e-3)
    assert hi["break_even_charge_cost"] == pytest.approx(1.0 / 0.95, rel=1e-3)


def test_arbitrage_gate_efficiency_clamped_to_supported_band():
    """eta_rt outside [0.50, 1.0] must be clamped, not extrapolated."""
    below = EconomicArbitrageGate.evaluate_arbitrage_viability(
        1.0, 5.0, 0.35, 0.01)
    at = EconomicArbitrageGate.evaluate_arbitrage_viability(
        1.0, 5.0, 0.35, 0.50)
    assert below["break_even_charge_cost"] == pytest.approx(at["break_even_charge_cost"])


# --------------------------------------------------------------------------
# IPMVP baseline edge cases
# --------------------------------------------------------------------------
def test_baseline_requires_three_days():
    with pytest.raises(ValueError, match="At least 3"):
        IpmvpBaselineEngine.calculate_10_in_10_baseline([[10.0] * 24, [11.0] * 24])


def test_baseline_averages_hourwise():
    days = [[100.0 + i] * 24 for i in range(5)]
    base = IpmvpBaselineEngine.calculate_10_in_10_baseline(days)
    assert base == pytest.approx([102.0] * 24)


def test_adjustment_clamped_to_max_fraction():
    base = np.full(24, 100.0)
    adjusted = IpmvpBaselineEngine.apply_same_day_adjustment(
        base, pre_event_actual_2h_kw=[1e6, 1e6], event_start_hour=10,
        max_adjustment_fraction=0.20,
    )
    # Ratio would be 10000x but must clamp to +20%
    assert adjusted[0] == pytest.approx(120.0)


def test_adjustment_negative_clamp():
    base = np.full(24, 100.0)
    adjusted = IpmvpBaselineEngine.apply_same_day_adjustment(
        base, pre_event_actual_2h_kw=[0.0, 0.0], event_start_hour=10,
    )
    assert adjusted[0] == pytest.approx(80.0)


def test_cv_rmse_zero_when_actual_is_flat():
    act = np.zeros(24)
    base = np.array([1.0] * 24)
    assert IpmvpBaselineEngine.calculate_cv_rmse(act, base) == 0.0


def test_cv_rmse_rejects_tiny_sample():
    with pytest.raises(ValueError, match="must exceed degrees"):
        IpmvpBaselineEngine.calculate_cv_rmse(np.array([1.0]), np.array([1.0]))


def test_nmbe_rejects_tiny_sample():
    with pytest.raises(ValueError, match="must exceed degrees"):
        IpmvpBaselineEngine.calculate_nmbe(np.array([1.0]), np.array([1.0]))


def test_savings_never_negative_when_actual_exceeds_baseline():
    """An event where the meter ran ABOVE baseline must report zero savings."""
    base = np.full(24, 100.0)
    actual = np.full(24, 150.0)
    ptf = np.full(24, 3.0)
    res = IpmvpBaselineEngine.compute_event_savings(base, actual, ptf, [12, 13])
    assert res["net_curtailed_kwh"] == 0.0
    assert res["net_financial_savings_try"] == 0.0


# --------------------------------------------------------------------------
# Ledger determinism / tamper-evidence
# --------------------------------------------------------------------------
def test_ledger_empty_root_is_stable():
    a = CryptographicSavingsLedger().compute_merkle_root()
    b = CryptographicSavingsLedger().compute_merkle_root()
    assert a == b and len(a) == 64


def test_ledger_root_changes_on_tamper():
    led = CryptographicSavingsLedger()
    led.append_entry({"event": "X", "kwh": 10})
    before = led.compute_merkle_root()
    led.entries[-1]["kwh"] = 11
    after = led.compute_merkle_root()
    assert before != after


def test_ledger_odd_entry_count_pads_last_leaf():
    led = CryptographicSavingsLedger()
    for i in range(3):
        led.append_entry({"event": f"e{i}"})
    root = led.compute_merkle_root()
    assert len(root) == 64 and set(root) <= set("0123456789abcdef")


# --------------------------------------------------------------------------
# Thevenin OCV piecewise segments
# --------------------------------------------------------------------------
def test_ocv_low_soc_branch():
    v = TheveninBatteryModel.calculate_ocv(0.02)
    assert v == pytest.approx(2.50 + 0.02 * 10.0)


def test_ocv_high_soc_branch():
    v = TheveninBatteryModel.calculate_ocv(0.98)
    assert v == pytest.approx(3.35 + 0.03 * 6.0)


def test_ocv_mid_plateau_is_flat():
    v_lo = TheveninBatteryModel.calculate_ocv(0.30)
    v_hi = TheveninBatteryModel.calculate_ocv(0.70)
    assert 3.15 <= v_lo <= 3.40
    assert 3.15 <= v_hi <= 3.40
    assert abs(v_hi - v_lo) < 0.10


def test_ocv_clamps_outside_unit_soc():
    assert TheveninBatteryModel.calculate_ocv(-5.0) == pytest.approx(2.50)
    assert TheveninBatteryModel.calculate_ocv(5.0) == pytest.approx(3.35 + 0.05 * 6.0)


def test_ecm_charge_raises_voltage_and_soc():
    m = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.50)
    v0, soc0 = m.step(current_a=-50.0, dt_seconds=3600.0)
    assert soc0 > 0.50          # charging increases SoC
    assert v0 > 3.0


def test_ecm_discharge_lowers_soc():
    m = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.50)
    _, soc = m.step(current_a=50.0, dt_seconds=3600.0)
    assert soc < 0.50


def test_ecm_soc_clamped_to_unit_interval():
    m = TheveninBatteryModel(nominal_capacity_ah=1.0, initial_soc=0.99)
    _, soc = m.step(current_a=-1000.0, dt_seconds=3600.0)
    assert soc <= 1.0
