"""
Unit tests for 2-RC Thevenin Battery Model.
"""

import pytest
from fleksa.battery.thevenin import TheveninBatteryModel


def test_ocv_calculation():
    # Test LFP plateau and boundaries
    ocv_empty = TheveninBatteryModel.calculate_ocv(0.0)
    ocv_mid = TheveninBatteryModel.calculate_ocv(0.50)
    ocv_full = TheveninBatteryModel.calculate_ocv(1.0)

    assert ocv_empty < 2.6
    assert 3.20 <= ocv_mid <= 3.35
    assert ocv_full > 3.40


def test_battery_discharge_step():
    model = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.80)
    # Discharge at 50A for 3600 seconds (1 hour) = 50 Ah discharged
    v_term, new_soc = model.step(current_a=50.0, dt_seconds=3600.0)

    assert round(new_soc, 2) == 0.30
    assert v_term < 3.30  # Terminal voltage drops under discharge current


def test_battery_charge_step():
    model = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.30)
    # Charge at 25A (-25A) for 3600 seconds = 25 Ah charged
    v_term, new_soc = model.step(current_a=-25.0, dt_seconds=3600.0)

    assert round(new_soc, 2) == 0.55
    assert v_term > 3.25  # Terminal voltage rises under charge current


def test_battery_arrhenius_temperature_dependence():
    # Warm cell (25°C) vs Cold cell (0°C) under identical discharge current
    model_warm = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.80)
    model_cold = TheveninBatteryModel(nominal_capacity_ah=100.0, initial_soc=0.80)

    v_warm, _ = model_warm.step(current_a=50.0, dt_seconds=60.0, temp_celsius=25.0)
    v_cold, _ = model_cold.step(current_a=50.0, dt_seconds=60.0, temp_celsius=0.0)

    # Cold battery has higher internal resistance, hence lower terminal voltage under discharge
    assert v_cold < v_warm
    assert (v_warm - v_cold) > 0.015  # Notable ohmic depression at 0°C

