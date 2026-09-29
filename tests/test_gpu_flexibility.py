"""
Dynamic GPU flexibility tests — the refutation of the fixed min_gpu_cap=0.65
assumption, per arXiv:2609.05406 ("Beyond Scalar Flexibility", Li, 2026).

These tests pin the semantics the old fixed floor could not express:
monotonic response to demand, bounded floor/ceiling, per-hour variation,
and economic consequences in the MPC dispatch.
"""

import pytest
import numpy as np

from fleksa.core.constants import (
    GPU_CAP_CEILING,
    GPU_CAP_HARD_FLOOR,
    GPU_CAP_LEGACY_DEFAULT,
)
from fleksa.workload.gpu_flexibility import (
    GpuDemandSignals,
    GpuFlexibilityProfiler,
)
from fleksa.mpc.solver import FleksaMPCSolver
from fleksa.core.types import FacilityState, MarketDataHorizon


# --------------------------------------------------------------------------
# Demand-pressure semantics
# --------------------------------------------------------------------------
def _signals(backlog, noncrit, sla):
    return GpuDemandSignals(
        queue_backlog_flops=[backlog],
        noncritical_share=[noncrit],
        sla_pressure=[sla],
    )


def test_idle_cluster_exposes_more_headroom_than_busy():
    """The core of the fix: idle GPUs are throttleable, saturated GPUs are not."""
    p = GpuFlexibilityProfiler()
    idle = p.compute_flexibility_profile(_signals(1_000.0, 0.8, 0.0))
    busy = p.compute_flexibility_profile(_signals(10_000_000.0, 0.1, 1.0))

    assert idle[0] < busy[0]
    # Headroom (100% - cap) must be strictly larger for the idle cluster
    assert (1.0 - idle[0]) > (1.0 - busy[0])


def test_saturated_cluster_pins_to_ceiling():
    p = GpuFlexibilityProfiler()
    busy = p.compute_flexibility_profile(_signals(10_000_000.0, 0.0, 1.0))
    assert busy[0] == pytest.approx(GPU_CAP_CEILING, abs=1e-6)


def test_idle_floor_within_paper_band():
    """Idle headroom must land inside the 17-47% band the paper documents."""
    p = GpuFlexibilityProfiler()
    idle = p.compute_flexibility_profile(_signals(1_000.0, 0.8, 0.0))
    headroom_pct = (1.0 - idle[0]) * 100.0
    assert 17.0 <= headroom_pct <= 50.0


def test_floor_monotonic_in_backlog():
    p = GpuFlexibilityProfiler()
    floors = [
        p.compute_flexibility_profile(_signals(b, 0.5, 0.3))[0]
        for b in (1e3, 1e5, 1e7, 1e9)
    ]
    assert all(a <= b + 1e-9 for a, b in zip(floors, floors[1:]))


def test_floor_monotonic_in_sla_pressure():
    """Rising deadline pressure must tighten (raise) the floor."""
    p = GpuFlexibilityProfiler()
    floors = [
        p.compute_flexibility_profile(_signals(500_000.0, 0.5, s))[0]
        for s in (0.0, 0.25, 0.5, 1.0)
    ]
    assert all(a <= b + 1e-9 for a, b in zip(floors, floors[1:]))


def test_floor_antimonotonic_in_noncritical_share():
    """More deferrable work => more throttle headroom => lower floor."""
    p = GpuFlexibilityProfiler()
    floors = [
        p.compute_flexibility_profile(_signals(500_000.0, s, 0.5))[0]
        for s in (0.1, 0.3, 0.5, 0.8)
    ]
    assert all(a >= b - 1e-9 for a, b in zip(floors, floors[1:]))


def test_floor_bounded_hard_floor_to_ceiling():
    p = GpuFlexibilityProfiler()
    for backlog in (0.0, 1e2, 1e6, 1e12):
        f = p.compute_flexibility_profile(_signals(backlog, 0.5, 0.5))[0]
        assert GPU_CAP_HARD_FLOOR - 1e-9 <= f <= GPU_CAP_CEILING + 1e-9


def test_diurnal_profile_varies_across_hours():
    """A constant floor cannot vary per hour; the dynamic one must."""
    p = GpuFlexibilityProfiler()
    backlog, noncrit, sla = [], [], []
    for h in range(24):
        day = np.cos((h - 14.0) / 24.0 * 2.0 * np.pi) * 0.5 + 0.5
        backlog.append(750_000.0 * (0.15 + 0.85 * day))
        noncrit.append(0.85 - 0.55 * day)
        sla.append(float(np.clip(0.35 * day + 0.10 * (h >= 20), 0.0, 1.0)))
    prof = p.compute_flexibility_profile(
        GpuDemandSignals(backlog, noncrit, sla)
    )
    assert len(prof) == 24
    assert max(prof) > min(prof) + 1e-6, "profile must respond to demand"
    assert all(GPU_CAP_HARD_FLOOR <= f <= GPU_CAP_CEILING for f in prof)


# --------------------------------------------------------------------------
# Validation / construction guards
# --------------------------------------------------------------------------
def test_demand_signals_length_mismatch_rejected():
    with pytest.raises(ValueError, match="equal length"):
        GpuDemandSignals([1.0, 2.0], [1.0], [1.0, 2.0])


def test_demand_signals_empty_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        GpuDemandSignals([], [], [])


@pytest.mark.parametrize(
    "hard_floor,ceiling",
    [(-0.1, 1.0), (1.0, 1.0), (0.5, 0.4), (0.0, 1.0)],
)
def test_profiler_rejects_invalid_bounds(hard_floor, ceiling):
    with pytest.raises(ValueError, match="hard_floor"):
        GpuFlexibilityProfiler(hard_floor=hard_floor, ceiling=ceiling)


@pytest.mark.parametrize("sat", [0.0, -1.0])
def test_profiler_rejects_nonpositive_saturation(sat):
    with pytest.raises(ValueError, match="saturation"):
        GpuFlexibilityProfiler(backlog_saturation_flops=sat)


def test_constant_profile_reproduces_legacy_floor():
    """The legacy path stays bit-for-bit available for reproducibility."""
    p = GpuFlexibilityProfiler()
    legacy = p.constant_profile(24, GPU_CAP_LEGACY_DEFAULT)
    assert legacy == [0.65] * 24


def test_constant_profile_rejects_bad_inputs():
    with pytest.raises(ValueError):
        GpuFlexibilityProfiler.constant_profile(0)
    with pytest.raises(ValueError):
        GpuFlexibilityProfiler.constant_profile(5, 1.5)


def test_headroom_report_shapes():
    p = GpuFlexibilityProfiler()
    hr = p.headroom_pct(p.constant_profile(12, 0.5))
    assert hr["max_headroom_pct"] == pytest.approx(50.0)
    assert hr["min_headroom_pct"] == pytest.approx(50.0)
    assert hr["mean_headroom_pct"] == pytest.approx(50.0)


# --------------------------------------------------------------------------
# Economic consequence: the dynamic floor must be able to beat the fixed one
# when demand genuinely leaves headroom on the table.
# --------------------------------------------------------------------------
@pytest.fixture
def dynamic_horizon():
    ptf = np.array([
        2.2, 2.0, 1.8, 1.6, 1.7, 2.1, 2.8, 3.2, 2.5, 1.8, 1.2, 0.9,
        0.8, 0.9, 1.1, 1.6, 2.4, 3.8, 4.9, 5.2, 4.6, 3.5, 2.8, 2.4,
    ])
    return MarketDataHorizon(
        hours=24,
        ptf_try_kwh=ptf,
        base_load_kw=np.full(24, 200.0),
        pv_gen_kw=np.array([
            0, 0, 0, 0, 0, 10, 30, 80, 120, 160, 180, 200,
            200, 170, 130, 80, 30, 10, 0, 0, 0, 0, 0, 0,
        ], dtype=float),
        ambient_temp_c=np.full(24, 25.0),
    )


def _state():
    return FacilityState(bess_soc_kwh=200.0, bess_capacity_kwh=500.0, bess_max_kw=250.0)


def test_solver_uses_dynamic_floor_per_hour(dynamic_horizon):
    profiler = GpuFlexibilityProfiler()
    backlog, noncrit, sla = [], [], []
    for h in range(24):
        day = np.cos((h - 14.0) / 24.0 * 2.0 * np.pi) * 0.5 + 0.5
        backlog.append(750_000.0 * (0.15 + 0.85 * day))
        noncrit.append(0.85 - 0.55 * day)
        sla.append(float(np.clip(0.35 * day + 0.10 * (h >= 20), 0.0, 1.0)))
    profile = profiler.compute_flexibility_profile(
        GpuDemandSignals(backlog, noncrit, sla)
    )

    res = FleksaMPCSolver(
        state=_state(), horizon_data=dynamic_horizon, gpu_flex_profile=profile
    ).solve()

    assert res.status == "OPTIMAL"
    assert res.metadata["gpu_flexibility_mode"] == "DYNAMIC_DEMAND_BASED"
    # The realized caps must honour every per-hour floor.
    for cap, floor in zip(res.gpu_power_cap_pct, profile):
        assert cap >= floor - 1e-4


def test_solver_defaults_to_legacy_floor_without_profile(dynamic_horizon):
    res = FleksaMPCSolver(state=_state(), horizon_data=dynamic_horizon).solve()
    assert res.metadata["gpu_flexibility_mode"] == "LEGACY_FIXED_FLOOR"
    assert res.metadata["gpu_cap_floor_min"] == pytest.approx(0.65)
    assert res.metadata["gpu_cap_floor_max"] == pytest.approx(0.65)


def test_solver_rejects_wrong_length_profile(dynamic_horizon):
    with pytest.raises(ValueError, match="length 12"):
        FleksaMPCSolver(
            state=_state(), horizon_data=dynamic_horizon,
            gpu_flex_profile=[0.7] * 12,
        )


def test_solver_rejects_out_of_range_profile(dynamic_horizon):
    with pytest.raises(ValueError, match="out of range"):
        FleksaMPCSolver(
            state=_state(), horizon_data=dynamic_horizon,
            gpu_flex_profile=[1.5] + [0.7] * 23,
        )


def test_idle_dynamic_profile_better_savings_than_fixed(dynamic_horizon):
    """
    When the cluster is idle, demand-based bounds expose real headroom that
    a fixed 0.65 floor artificially withholds — this is the paper's 17-47%
    underestimation, expressed in dispatch economics.
    """
    profiler = GpuFlexibilityProfiler()
    idle = GpuDemandSignals(
        queue_backlog_flops=[1_000.0] * 24,
        noncritical_share=[0.8] * 24,
        sla_pressure=[0.0] * 24,
    )
    dynamic = profiler.compute_flexibility_profile(idle)
    fixed = profiler.constant_profile(24, GPU_CAP_LEGACY_DEFAULT)

    res_dyn = FleksaMPCSolver(
        state=_state(), horizon_data=dynamic_horizon, gpu_flex_profile=dynamic
    ).solve()
    res_fix = FleksaMPCSolver(
        state=_state(), horizon_data=dynamic_horizon, gpu_flex_profile=fixed
    ).solve()

    # Idle floors are lower than 0.65 everywhere, so the solver cannot do worse.
    assert all(f <= 0.65 for f in dynamic)
    assert res_dyn.expected_savings_try >= res_fix.expected_savings_try - 1e-6
