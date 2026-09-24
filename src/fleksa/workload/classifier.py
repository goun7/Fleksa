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

    def __init__(self):
        self.jobs: Dict[str, ComputeJob] = {}

    def register_job(self, job: ComputeJob) -> None:
        self.jobs[job.job_id] = job

    def total_active_power_kw(self) -> float:
        return sum(job.current_power_kw for job in self.jobs.values() if not job.is_paused)

    def dispatch_power_limit(self, target_power_budget_kw: float) -> Dict[str, Any]:
        """
        Adjusts job states to meet target_power_budget_kw respecting priority order:
        Class-0: Never paused, never throttled
        Class-1: Postponed if needed
        Class-2: Checkpointed and paused if needed
        Class-3: Power capped down to 65% first
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

        # Step 1: Throttle Class-3 workloads down to 65%
        for job in self.jobs.values():
            if job.load_class == LoadClass.CLASS_3_THROTTLABLE and not job.is_paused:
                job.power_cap_fraction = 0.65
                job.current_power_kw = job.nominal_power_kw * 0.65
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
