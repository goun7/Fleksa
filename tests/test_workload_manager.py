"""
Unit tests for compute workload scheduling and GPU power capping.
"""

import pytest
from fleksa.core.types import LoadClass
from fleksa.workload.classifier import ComputeJob, WorkloadScheduler
from fleksa.workload.power_cap import GpuPowerCapSimulator
from fleksa.workload.speculative import DynamicSpeculativeOptimizer


def test_workload_scheduler_priority_curtailment():
    scheduler = WorkloadScheduler()

    # Register Class-0 (Critical, 100 kW)
    job0 = ComputeJob("job-db", LoadClass.CLASS_0_CRITICAL, nominal_power_kw=100.0, current_power_kw=100.0)
    # Register Class-3 (Throttlable, 100 kW)
    job3 = ComputeJob("job-inf", LoadClass.CLASS_3_THROTTLABLE, nominal_power_kw=100.0, current_power_kw=100.0)
    # Register Class-2 (Preemptible LLM, 150 kW)
    job2 = ComputeJob("job-train", LoadClass.CLASS_2_PREEMPTIBLE, nominal_power_kw=150.0, current_power_kw=150.0)

    scheduler.register_job(job0)
    scheduler.register_job(job3)
    scheduler.register_job(job2)

    assert scheduler.total_active_power_kw() == 350.0

    # Step 1: Reduce budget to 320 kW -> Class-3 throttles to 65% (saves 35 kW -> 315 kW total)
    res1 = scheduler.dispatch_power_limit(target_power_budget_kw=320.0)
    assert res1["status"] == "THROTTLED"
    assert scheduler.total_active_power_kw() <= 320.0
    assert not job0.is_paused
    assert not job2.is_paused
    assert job3.power_cap_fraction == 0.65

    # Step 2: Severe curtailment: Reduce budget to 170 kW -> Class-2 (150 kW) must be paused!
    # Remaining: Job0 (100 kW) + Job3 (65 kW) = 165 kW <= 170 kW
    res2 = scheduler.dispatch_power_limit(target_power_budget_kw=170.0)
    assert res2["status"] == "CLASS_2_PAUSED"
    assert job2.is_paused
    assert job2.current_power_kw == 0.0
    # Class-0 is NEVER paused
    assert not job0.is_paused

    # Step 3: Budget increases back to 400 kW -> Resume all paused jobs!
    res3 = scheduler.dispatch_power_limit(target_power_budget_kw=400.0)
    assert res3["status"] == "BUDGET_MET"
    assert not job2.is_paused


def test_workload_scheduler_defer_class_1():
    scheduler = WorkloadScheduler()
    job0 = ComputeJob("job-0", LoadClass.CLASS_0_CRITICAL, nominal_power_kw=100.0, current_power_kw=100.0)
    job1 = ComputeJob("job-1", LoadClass.CLASS_1_DEFERRABLE, nominal_power_kw=50.0, current_power_kw=50.0)
    scheduler.register_job(job0)
    scheduler.register_job(job1)

    # Budget 110 kW -> job1 must be deferred
    res = scheduler.dispatch_power_limit(target_power_budget_kw=110.0)
    assert res["status"] == "LOAD_SHED"
    assert job1.is_paused
    assert not job0.is_paused


def test_gpu_power_capping_sublinear_tradeoff():
    res = GpuPowerCapSimulator.calculate_efficiency("H100_SXM5", target_power_w=450.0)

    assert res["nominal_w"] == 700.0
    assert res["applied_w"] == 450.0
    assert res["power_reduction_pct"] > 35.0
    # Throughput drops much less (<15%) due to memory-bound kernel characteristics
    assert res["throughput_loss_pct"] < 15.0
    assert res["efficiency_gain_pct"] > 30.0


def test_dynamic_speculative_optimizer():
    # Peak price: should return ECO mode
    opt_peak = DynamicSpeculativeOptimizer.optimize_parameters(ptf_try_kwh=5.0)
    assert opt_peak["operating_mode"] == "ECO_CONSERVE"
    assert opt_peak["draft_length"] == 2
    assert opt_peak["recommended_power_cap_w"] == 450.0

    # Off-peak price: should return MAX_THROUGHPUT
    opt_trough = DynamicSpeculativeOptimizer.optimize_parameters(ptf_try_kwh=1.2)
    assert opt_trough["operating_mode"] == "MAX_THROUGHPUT"
    assert opt_trough["draft_length"] == 5
    assert opt_trough["recommended_power_cap_w"] == 700.0
