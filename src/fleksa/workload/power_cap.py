"""
NVIDIA NVML / DCGM Dynamic Power Capping and DVFS Efficiency Simulator.
"""

from typing import Dict, Any


class GpuPowerCapSimulator:
    """
    Models the non-linear relationship between GPU power capping (TDP)
    and compute throughput for memory-bound LLM and dense matrix multiplication workloads.
    """

    GPU_SPECS = {
        "H100_SXM5": {"nominal_tdp_w": 700.0, "min_tdp_w": 350.0, "alpha_memory_bound": 0.35},
        "H100_PCIE": {"nominal_tdp_w": 350.0, "min_tdp_w": 200.0, "alpha_memory_bound": 0.32},
        "H200_SXM5": {"nominal_tdp_w": 700.0, "min_tdp_w": 350.0, "alpha_memory_bound": 0.33},
        "B200_NVL":  {"nominal_tdp_w": 1000.0, "min_tdp_w": 500.0, "alpha_memory_bound": 0.36},
    }

    @classmethod
    def calculate_efficiency(cls, model_name: str, target_power_w: float) -> Dict[str, float]:
        spec = cls.GPU_SPECS.get(model_name, cls.GPU_SPECS["H100_SXM5"])
        nom_w = spec["nominal_tdp_w"]
        min_w = spec["min_tdp_w"]
        alpha = spec["alpha_memory_bound"]

        applied_w = max(min_w, min(nom_w, target_power_w))
        cap_fraction = applied_w / nom_w
        power_reduction_pct = (1.0 - cap_fraction) * 100.0

        # Memory-bound kernel throughput drops much less than power reduction
        throughput_loss_pct = (1.0 - cap_fraction) * alpha * 100.0
        relative_throughput = 1.0 - (throughput_loss_pct / 100.0)

        # Performance-per-Watt improvement
        perf_per_watt_relative = relative_throughput / cap_fraction
        efficiency_gain_pct = (perf_per_watt_relative - 1.0) * 100.0

        return {
            "model_name": model_name,
            "nominal_w": nom_w,
            "applied_w": applied_w,
            "power_reduction_pct": round(power_reduction_pct, 2),
            "throughput_loss_pct": round(throughput_loss_pct, 2),
            "relative_throughput": round(relative_throughput, 4),
            "efficiency_gain_pct": round(efficiency_gain_pct, 2),
        }
