"""
Dynamic GPU Flexibility Profiler  (rebuttal to arXiv:2609.05406).

The original Fleksa MPC used a *fixed* per-hour GPU power-cap floor
(``min_gpu_cap = 0.65``).  arXiv:2609.05406 analysed a 155,410-GPU
production trace and showed that a constant-percentage flexibility floor
*underestimates* real, demand-observable flexibility by 17-47%: GPUs are
far more throttling-tolerant when their own queues are shallow, and far
less when they are saturated.

This module replaces the constant floor with a **demand-based** one.
For every hour of the optimisation horizon it computes the lowest
power-cap fraction a GPU fleet can safely be driven to, given how much
work is actually queued behind it and how much of that work is
deadline-tolerant.

Bounds
------
cap_floor_t ∈ [GPU_CAP_HARD_FLOOR (0.50), GPU_CAP_CEILING (1.0)]

high demand pressure  →  cap_floor → 1.0   (no throttling headroom)
low  demand pressure  →  cap_floor → 0.50  (maximum throttling headroom)

The mapping is a bounded power law in a normalized "demand pressure"
index, whose exponent is calibrated so the resulting headroom spans the
17-47% band reported by the refuting paper instead of the single ~35%
point implied by the old fixed 0.65 floor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from fleksa.core.constants import (
    GPU_CAP_CEILING,
    GPU_CAP_HARD_FLOOR,
    GPU_CAP_LEGACY_DEFAULT,
    GPU_FLEX_BACKLOG_SATURATION_FLOPS,
    GPU_FLEX_ELASTICITY_EXPONENT,
    GPU_FLEX_MAX_NONCRITICAL_SHARE,
)

logger = logging.getLogger("Fleksa.GpuFlexibility")


@dataclass(frozen=True)
class GpuDemandSignals:
    """
    Per-hour demand telemetry that drives GPU flexibility.

    All sequences must share the same length ``hours``.

    queue_backlog_flops   : pending FLOPS queued for the fleet (work awaiting GPUs)
    noncritical_share     : fraction of queued work that is Class-1/2/3
                            (deferrable / preemptible / throttling-tolerant),
                            in [0.0, 1.0].  Critical Class-0 work cannot absorb
                            throttling, so it tightens the floor.
    sla_pressure          : normalized deadline pressure in [0.0, 1.0];
                            1.0 = all queued work is at/near its SLA deadline.
    """

    queue_backlog_flops: Sequence[float]
    noncritical_share: Sequence[float]
    sla_pressure: Sequence[float]

    def __post_init__(self) -> None:
        n = len(self.queue_backlog_flops)
        if not (len(self.noncritical_share) == n == len(self.sla_pressure)):
            raise ValueError(
                "GpuDemandSignals: all demand sequences must have equal length "
                f"(got {len(self.queue_backlog_flops)}, "
                f"{len(self.noncritical_share)}, {len(self.sla_pressure)})"
            )
        if n == 0:
            raise ValueError("GpuDemandSignals: demand sequences must be non-empty")


class GpuFlexibilityProfiler:
    """
    Demand-based hourly GPU power-cap floor.

    ``compute_flexibility_profile`` converts per-hour demand signals into a
    per-hour lower bound on the GPU power-cap fraction.  This profile is fed
    to :class:`fleksa.mpc.solver.FleksaMPCSolver` in place of the legacy
    constant ``min_gpu_cap``.
    """

    def __init__(
        self,
        hard_floor: float = GPU_CAP_HARD_FLOOR,
        ceiling: float = GPU_CAP_CEILING,
        backlog_saturation_flops: float = GPU_FLEX_BACKLOG_SATURATION_FLOPS,
        max_noncritical_share: float = GPU_FLEX_MAX_NONCRITICAL_SHARE,
        elasticity_exponent: float = GPU_FLEX_ELASTICITY_EXPONENT,
    ) -> None:
        if not (0.0 < hard_floor < ceiling <= 1.0):
            raise ValueError(
                "GpuFlexibilityProfiler: require 0 < hard_floor < ceiling <= 1, "
                f"got hard_floor={hard_floor}, ceiling={ceiling}"
            )
        if backlog_saturation_flops <= 0.0:
            raise ValueError("GpuFlexibilityProfiler: backlog_saturation_flops must be > 0")
        if not (0.0 < max_noncritical_share <= 1.0):
            raise ValueError("GpuFlexibilityProfiler: max_noncritical_share must be in (0, 1]")
        if elasticity_exponent <= 0.0:
            raise ValueError("GpuFlexibilityProfiler: elasticity_exponent must be > 0")

        self.hard_floor = hard_floor
        self.ceiling = ceiling
        self.backlog_saturation_flops = backlog_saturation_flops
        self.max_noncritical_share = max_noncritical_share
        self.elasticity_exponent = elasticity_exponent

    # ------------------------------------------------------------------
    # Demand-pressure index
    # ------------------------------------------------------------------
    def demand_pressure(self, signals: GpuDemandSignals) -> list[float]:
        """
        Normalize demand signals into a per-hour pressure index in [0, 1].

        pressure = backlog_term * (1 - absorbable_term) * (1 + sla_term)

        * backlog_term saturates once the queue exceeds
          ``backlog_saturation_flops`` (half-saturation point).
        * absorbable_term discounts pressure by the share of queued work
          that can absorb throttling (deferrable/preemptible), scaled by
          ``max_noncritical_share``.
        * sla_term tightens pressure as deadlines approach.
        """
        backlog = np.asarray(signals.queue_backlog_flops, dtype=float)
        noncrit = np.clip(
            np.asarray(signals.noncritical_share, dtype=float), 0.0, 1.0
        )
        sla = np.clip(np.asarray(signals.sla_pressure, dtype=float), 0.0, 1.0)

        # Saturating (Michaelis-Menten style) backlog term in [0, 1]
        backlog_term = backlog / (backlog + self.backlog_saturation_flops)

        # Absorbable headroom: only noncritical work can absorb throttling
        absorbable = np.clip(noncrit / self.max_noncritical_share, 0.0, 1.0)
        # absorbable==1 -> pressure scaled to 0.15 (residual critical headroom)
        absorbable_term = 0.85 * absorbable

        sla_term = sla  # already in [0, 1]

        pressure = backlog_term * (1.0 - absorbable_term) * (1.0 + sla_term)
        # Residual floor so an idle cluster is not fully pinned at the ceiling
        pressure = 0.05 + 0.95 * np.clip(pressure, 0.0, 1.0)
        return [float(p) for p in pressure]

    # ------------------------------------------------------------------
    # Flexibility profile
    # ------------------------------------------------------------------
    def compute_flexibility_profile(self, signals: GpuDemandSignals) -> list[float]:
        """
        Map demand signals to a per-hour GPU power-cap floor.

        Monotonicity (the whole point of the fix): demand pressure is the
        *inverse* of throttling headroom. A cluster with a deep queue of
        deadline-bound work cannot be throttled, so pressure must push the
        cap floor **toward the ceiling**; an idle cluster must drop toward
        the hard floor. The direction is therefore ``floor = hard_floor +
        span * pressure``, not ``ceiling - span * pressure``.

        Returns a list of length ``len(signals)`` with values in
        [hard_floor, ceiling].
        """
        pressure = np.asarray(self.demand_pressure(signals), dtype=float)
        span = self.ceiling - self.hard_floor
        # Bounded power law: headroom shrinks super-linearly with pressure
        cap_floor = self.hard_floor + span * np.power(pressure, self.elasticity_exponent)
        profile = [float(np.clip(c, self.hard_floor, self.ceiling)) for c in cap_floor]

        logger.debug(
            "GPU flexibility profile computed for %d hours: min=%.3f max=%.3f mean=%.3f",
            len(profile),
            min(profile),
            max(profile),
            sum(profile) / len(profile),
        )
        return profile

    # ------------------------------------------------------------------
    # Legacy interop
    # ------------------------------------------------------------------
    @staticmethod
    def constant_profile(hours: int, min_gpu_cap: float = GPU_CAP_LEGACY_DEFAULT) -> list[float]:
        """
        Backward-compatible constant floor (the refuted assumption).

        Kept only so legacy callers and the fixed-floor baseline stay
        reproducible; new code should use a demand-based profile.
        """
        if hours <= 0:
            raise ValueError("GpuFlexibilityProfiler.constant_profile: hours must be > 0")
        if not (0.0 < min_gpu_cap <= 1.0):
            raise ValueError("GpuFlexibilityProfiler.constant_profile: min_gpu_cap must be in (0, 1]")
        return [float(min_gpu_cap)] * hours

    def headroom_pct(self, profile: Sequence[float]) -> dict[str, float]:
        """
        Report how much throttling headroom a profile exposes, in percent.

        This is the diagnostic that exposes the 17-47% underestimation of
        the old fixed floor: compare ``fixed.headroom_pct`` against
        ``dynamic.headroom_pct`` for the same demand.
        """
        if not profile:
            raise ValueError("GpuFlexibilityProfiler.headroom_pct: profile must be non-empty")
        arr = np.asarray(profile, dtype=float)
        return {
            "min_headroom_pct": round(float((1.0 - arr.max()) * 100.0), 2),
            "max_headroom_pct": round(float((1.0 - arr.min()) * 100.0), 2),
            "mean_headroom_pct": round(float((1.0 - arr.mean()) * 100.0), 2),
            "min_cap_fraction": round(float(arr.min()), 4),
            "max_cap_fraction": round(float(arr.max()), 4),
        }
