"""
Compute Workload Classifier and Priority Scheduler for Fleksa.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from fleksa.core.types import LoadClass


@dataclass
class ComputeJob:
    job_id: str
    load_class: LoadClass
    nominal_power_kw: float
    current_power_kw: float
    is_paused: bool = False
    power_cap_fraction: float = 1.0
    sla_deadline_epoch: Optional[float] = None


class WorkloadScheduler:
    """
    Schedules and throttles compute workloads based on dynamic grid power constraints.
    """

    def __init__(self, eco_cap_fraction: float = 0.65):
        """
        Args:
            eco_cap_fraction: legacy fixed Class-3 throttle floor, kept for
                backward compatibility. arXiv:2609.05406 refuted the fixed
                0.65 floor (17-47% underestimation of real GPU flexibility);
                prefer passing a demand-based profile to
                :meth:`dispatch_power_limit` instead.
        """
        self.jobs: Dict[str, ComputeJob] = {}
        if not (0.0 < eco_cap_fraction <= 1.0):
            raise ValueError(
                f"eco_cap_fraction must be in (0, 1], got {eco_cap_fraction}"
            )
        self.eco_cap_fraction = eco_cap_fraction

    def register_job(self, job: ComputeJob) -> None:
        self.jobs[job.job_id] = job

    def total_active_power_kw(self) -> float:
        return sum(job.current_power_kw for job in self.jobs.values() if not job.is_paused)

    def dispatch_power_limit(
        self,
        target_power_budget_kw: float,
        eco_cap_profile: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Adjusts job states to meet target_power_budget_kw respecting priority order:
        Class-0: Never paused, never throttled
        Class-1: Postponed if needed
        Class-2: Checkpointed and paused if needed
        Class-3: Power capped down (legacy 0.65 floor, or demand-based) first

        Args:
            target_power_budget_kw: grid power budget to fit within.
            eco_cap_profile: optional demand-based per-job throttle floor
                (job_id -> fraction in (0, 1]) overriding the legacy constant
                :pyattr:`eco_cap_fraction`. This is the dynamic-GPU-flexibility
                path replacing the refuted fixed 0.65 floor (arXiv:2609.05406).
        """
        current_total = self.total_active_power_kw()
        actions = []

        if current_total <= target_power_budget_kw:
            # Power budget is sufficient, resume paused non-critical jobs
            for job in sorted(self.jobs.values(), key=lambda j: j.load_class.value):
                if job.is_paused:
                    job.is_paused = False
                    job.current_power_kw = job.nominal_power_kw * job.power_cap_fraction
                    actions.append({"job_id": job.job_id, "action": "RESUME"})
            return {"status": "BUDGET_MET", "total_power_kw": self.total_active_power_kw(), "actions": actions}

        # Step 1: Throttle Class-3 workloads down to their demand-based floor
        for job in self.jobs.values():
            if job.load_class == LoadClass.CLASS_3_THROTTLABLE and not job.is_paused:
                if eco_cap_profile is not None and job.job_id in eco_cap_profile:
                    floor = float(eco_cap_profile[job.job_id])
                    if not (0.0 < floor <= 1.0):
                        raise ValueError(
                            f"eco_cap_profile[{job.job_id!r}]={floor} out of range (0, 1]"
                        )
                    job.power_cap_fraction = floor
                    job.current_power_kw = job.nominal_power_kw * floor
                    actions.append(
                        {"job_id": job.job_id, "action": "APPLY_DYNAMIC_ECO_CAP",
                         "cap_fraction": job.power_cap_fraction}
                    )
                else:
                    job.power_cap_fraction = self.eco_cap_fraction
                    job.current_power_kw = job.nominal_power_kw * self.eco_cap_fraction
                    actions.append({"job_id": job.job_id, "action": "APPLY_ECO_CAP_65_PCT"})

        if self.total_active_power_kw() <= target_power_budget_kw:
            return {"status": "THROTTLED", "total_power_kw": self.total_active_power_kw(), "actions": actions}

        # Step 2: Pause Class-2 (Preemptible LLM Training)
        for job in self.jobs.values():
            if job.load_class == LoadClass.CLASS_2_PREEMPTIBLE and not job.is_paused:
                job.is_paused = True
                job.current_power_kw = 0.0
                actions.append({"job_id": job.job_id, "action": "CHECKPOINT_AND_PAUSE"})
                if self.total_active_power_kw() <= target_power_budget_kw:
                    break

        if self.total_active_power_kw() <= target_power_budget_kw:
            return {"status": "CLASS_2_PAUSED", "total_power_kw": self.total_active_power_kw(), "actions": actions}

        # Step 3: Postpone Class-1 (Deferrable Batch/ETL)
        for job in self.jobs.values():
            if job.load_class == LoadClass.CLASS_1_DEFERRABLE and not job.is_paused:
                job.is_paused = True
                job.current_power_kw = 0.0
                actions.append({"job_id": job.job_id, "action": "DEFER_QUEUE"})
                if self.total_active_power_kw() <= target_power_budget_kw:
                    break

        return {
            "status": "LOAD_SHED",
            "total_power_kw": self.total_active_power_kw(),
            "actions": actions,
            "budget_met": self.total_active_power_kw() <= target_power_budget_kw,
        }
