"""
Dynamic GPU-cap *range* tests — 2nd-wave academic rebuttal (2026).

The fixed ``min_gpu_cap = 0.65`` threshold was invalidated by:

* arXiv:2609.27926 ("Joule Point"): energy-per-inference is U-shaped in the
  power cap and the optimum is *workload-dependent* (~43-46% of peak on large
  GPUs) — "high utilization = efficient" is wrong.
* arXiv:2608.07971 ("ElastiCo"): static partitions cause underutilization.
* arXiv:2609.16682 ("DeepShare"): assurance is a continuous, demand-driven
  signal (70.58% utilization, -46% latency) rather than a fixed quota.

The solver now selects the GPU cap floor from a *dynamic range*
``[min_gpu_cap = 0.35, max_gpu_cap = 0.95]`` based on workload. Backward
compatibility is preserved: with no dynamic input, the legacy fixed 0.65
floor is returned — not a breaking change.
"""

import pytest
import numpy as np

from fleksa.core.constants import (
    GPU_CAP_DYNAMIC_MAX,
    GPU_CAP_DYNAMIC_MIN,
    GPU_CAP_LEGACY_DEFAULT,
)
from fleksa.mpc.solver import FleksaMPCSolver
from fleksa.core.types import FacilityState, MarketDataHorizon


@pytest.fixture
def horizon():
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


def test_solver_defaults_to_legacy_fixed_floor(horizon):
    """Backward compatibility: no dynamic_gpu_cap -> legacy 0.65 floor (NOT breaking)."""
    res = FleksaMPCSolver(state=_state(), horizon_data=horizon).solve()
    assert res.metadata["gpu_flexibility_mode"] == "LEGACY_FIXED_FLOOR"
    assert res.metadata["gpu_cap_floor_min"] == pytest.approx(GPU_CAP_LEGACY_DEFAULT)
    assert res.metadata["gpu_cap_floor_max"] == pytest.approx(0.65)


def test_dynamic_range_covers_joule_point_optimum(horizon):
    """Joule Point (arXiv:2609.27926): the workload-dependent energy optimum sits
    at 43-46% of peak on large GPUs — the dynamic range [0.35, 0.95] must
    contain that whole band, and a mid-workload selection must stay in range."""
    assert GPU_CAP_DYNAMIC_MIN <= 0.43
    assert 0.46 <= GPU_CAP_DYNAMIC_MAX
    assert GPU_CAP_DYNAMIC_MIN == pytest.approx(0.35)
    assert GPU_CAP_DYNAMIC_MAX == pytest.approx(0.95)
    # A mid-workload selection also lands inside the range (ElastiCo: flex, don't fix).
    cap = FleksaMPCSolver.select_dynamic_gpu_cap(0.5)
    assert GPU_CAP_DYNAMIC_MIN <= cap <= GPU_CAP_DYNAMIC_MAX


def test_dynamic_gpu_cap_outside_range_is_rejected(horizon):
    """A selected cap value outside [min_gpu_cap, max_gpu_cap] must be rejected —
    the whole point of the range (ElastiCo: static/out-of-place partitions fail)."""
    with pytest.raises(ValueError, match="outside the dynamic range"):
        FleksaMPCSolver(state=_state(), horizon_data=horizon, dynamic_gpu_cap=0.20)
    with pytest.raises(ValueError, match="outside the dynamic range"):
        FleksaMPCSolver(state=_state(), horizon_data=horizon, dynamic_gpu_cap=1.50)


def test_high_workload_selects_higher_capacity(horizon):
    """DeepShare (arXiv:2609.16682): the continuous assurance signal must map
    high workload -> high capacity; a saturated cluster needs it."""
    idle = FleksaMPCSolver.select_dynamic_gpu_cap(0.0)
    busy = FleksaMPCSolver.select_dynamic_gpu_cap(1.0)
    assert idle == pytest.approx(GPU_CAP_DYNAMIC_MIN)
    assert busy == pytest.approx(GPU_CAP_DYNAMIC_MAX)
    assert busy > idle
    caps = [FleksaMPCSolver.select_dynamic_gpu_cap(w) for w in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(a <= b + 1e-12 for a, b in zip(caps, caps[1:]))

    # Solver-level: a high-workload floor must bind the realized dispatch.
    res_hi = FleksaMPCSolver(
        state=_state(), horizon_data=horizon, dynamic_gpu_cap=busy
    ).solve()
    assert res_hi.status == "OPTIMAL"
    assert res_hi.metadata["gpu_flexibility_mode"] == "DYNAMIC_RANGE"
    assert res_hi.metadata["gpu_cap_floor_max"] == pytest.approx(busy)
    for realized in res_hi.gpu_power_cap_pct:
        assert realized >= busy - 1e-4


def test_solver_honors_joule_point_optimum_floor(horizon):
    """A workload-selected cap inside the Joule Point band (43-46%) is legal and
    becomes the realized per-hour floor of the dispatch."""
    # workload 0.15 -> 0.35 + 0.60 * 0.15 = 0.44, inside the 43-46% band.
    cap = FleksaMPCSolver.select_dynamic_gpu_cap(0.15)
    assert 0.43 <= cap <= 0.46
    res = FleksaMPCSolver(
        state=_state(), horizon_data=horizon, dynamic_gpu_cap=cap
    ).solve()
    assert res.status == "OPTIMAL"
    assert res.metadata["gpu_flexibility_mode"] == "DYNAMIC_RANGE"
    assert res.metadata["gpu_cap_floor_min"] == pytest.approx(cap)
    assert res.metadata["gpu_cap_dynamic_range"] == [
        pytest.approx(0.35), pytest.approx(0.95),
    ]
    for realized in res.gpu_power_cap_pct:
        assert realized >= cap - 1e-4
