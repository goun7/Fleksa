"""
Unit tests for battery degradation and thermal model.
"""

import pytest
from fleksa.battery.degradation import BatteryDegradationEngine
from fleksa.core.errors import SafetyGuardViolationError


def test_capacity_loss_wang():
    engine = BatteryDegradationEngine()
    loss_low = engine.compute_capacity_loss_pct(c_rate=0.5, temp_celsius=25.0, cumulative_ah=1000.0)
    loss_high = engine.compute_capacity_loss_pct(c_rate=2.0, temp_celsius=40.0, cumulative_ah=1000.0)

    assert loss_low > 0.0
    assert loss_high > loss_low  # Higher C-rate and temp accelerate aging


def test_marginal_cost_dod_progression():
    engine = BatteryDegradationEngine()
    cost_shallow = engine.marginal_cost_per_kwh(depth_of_discharge_pct=15.0)
    cost_mid = engine.marginal_cost_per_kwh(depth_of_discharge_pct=60.0)
    cost_deep = engine.marginal_cost_per_kwh(depth_of_discharge_pct=90.0)

    assert cost_shallow < cost_mid < cost_deep
    assert cost_shallow == 0.15
    assert cost_deep == 1.35


def test_thermal_step_and_cutoff():
    engine = BatteryDegradationEngine()
    # Normal temperature step under mild heat dissipation
    t_new = engine.thermal_step(current_temp_c=25.0, ambient_temp_c=25.0, power_loss_watts=500.0, dt_seconds=60.0)
    assert t_new > 25.0

    # Overheating thermal safety trip
    with pytest.raises(SafetyGuardViolationError, match="Thermal cutoff breached"):
        engine.thermal_step(current_temp_c=44.9, ambient_temp_c=35.0, power_loss_watts=50000.0, dt_seconds=300.0)


def test_calendar_and_total_degradation():
    engine = BatteryDegradationEngine()
    cal_loss_30d = engine.compute_calendar_loss_pct(temp_celsius=25.0, average_soc=0.50, days=30.0)
    cal_loss_365d = engine.compute_calendar_loss_pct(temp_celsius=25.0, average_soc=0.50, days=365.0)
    cal_loss_hot = engine.compute_calendar_loss_pct(temp_celsius=40.0, average_soc=0.50, days=30.0)
    cal_loss_high_soc = engine.compute_calendar_loss_pct(temp_celsius=25.0, average_soc=0.95, days=30.0)

    assert cal_loss_30d > 0.0
    assert cal_loss_365d > cal_loss_30d  # Time sqrt dependence
    assert cal_loss_hot > cal_loss_30d   # Arrhenius temperature dependence
    assert cal_loss_high_soc > cal_loss_30d  # SoC stress dependence

    total_loss = engine.compute_total_capacity_loss_pct(
        c_rate=1.0, temp_celsius=25.0, cumulative_ah=1000.0, average_soc=0.50, days=30.0
    )
    cycle_loss = engine.compute_capacity_loss_pct(c_rate=1.0, temp_celsius=25.0, cumulative_ah=1000.0)
    assert total_loss == pytest.approx(cycle_loss + cal_loss_30d, rel=1e-5)
