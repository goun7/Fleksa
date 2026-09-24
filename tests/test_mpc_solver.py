"""
Unit and integration tests for Fleksa Receding Horizon MPC Solver.
"""

import pytest
import numpy as np
from fleksa.core.types import FacilityState, MarketDataHorizon
from fleksa.mpc.solver import FleksaMPCSolver


def test_mpc_solver_basic(sample_facility_state, sample_horizon_data):
    solver = FleksaMPCSolver(state=sample_facility_state, horizon_data=sample_horizon_data)
    res = solver.solve()

    assert res.status == "OPTIMAL"
    assert len(res.p_ch_kw) == 24
    assert len(res.p_dis_kw) == 24
    assert len(res.p_grid_kw) == 24
    assert len(res.soc_trajectory_kwh) == 25
    assert len(res.gpu_power_cap_pct) == 24

    # Savings must be positive vs flat baseline
    assert res.expected_savings_try > 0.0


def test_mpc_soc_limits_respected(sample_facility_state, sample_horizon_data):
    solver = FleksaMPCSolver(state=sample_facility_state, horizon_data=sample_horizon_data)
    res = solver.solve()

    min_soc = sample_facility_state.bess_capacity_kwh * sample_facility_state.min_soc_pct
    max_soc = sample_facility_state.bess_capacity_kwh * sample_facility_state.max_soc_pct

    for soc_val in res.soc_trajectory_kwh:
        assert soc_val >= min_soc - 1e-4
        assert soc_val <= max_soc + 1e-4


def test_mpc_mutual_exclusion(sample_facility_state, sample_horizon_data):
    solver = FleksaMPCSolver(state=sample_facility_state, horizon_data=sample_horizon_data)
    res = solver.solve()

    for ch, dis in zip(res.p_ch_kw, res.p_dis_kw):
        # Battery cannot charge and discharge simultaneously
        assert not (ch > 1.0 and dis > 1.0)


def test_mpc_charges_in_trough_and_discharges_in_peak(sample_facility_state, sample_horizon_data):
    solver = FleksaMPCSolver(state=sample_facility_state, horizon_data=sample_horizon_data)
    res = solver.solve()

    # In duck curve, hours 11-13 have lowest prices (0.8 - 0.9 TL/kWh) + high PV
    trough_charging = sum(res.p_ch_kw[10:14])
    assert trough_charging > 50.0  # Must charge significantly during trough

    # Hours 18-20 have highest prices (4.9 - 5.2 TL/kWh)
    peak_discharging = sum(res.p_dis_kw[18:21])
    assert peak_discharging > 50.0  # Must discharge significantly during peak


def test_mpc_water_cooling_footprint_penalty(sample_facility_state, sample_horizon_data):
    from fleksa.core.constants import DEFAULT_WATER_LITER_PER_KWH, DEFAULT_WATER_COST_TRY_PER_LITER

    water_kwh_cost = DEFAULT_WATER_LITER_PER_KWH * DEFAULT_WATER_COST_TRY_PER_LITER
    solver_water = FleksaMPCSolver(
        state=sample_facility_state,
        horizon_data=sample_horizon_data,
        water_cost_per_kwh=water_kwh_cost
    )
    res_water = solver_water.solve()
    assert res_water.status == "OPTIMAL"
    assert res_water.expected_savings_try > 0.0
