"""
Physical, chemical, electrical, and market constants for Fleksa.
"""

# Universal Gas Constant (J / (mol * K))
GAS_CONSTANT_R: float = 8.314462618

# LFP (LiFePO4) Arrhenius Activation Energy (J / mol)
LFP_ACTIVATION_ENERGY_EA: float = 31700.0

# Wang Degradation Empirical Coefficients
WANG_ALPHA_C_RATE: float = 0.0032
WANG_B_BASE: float = 0.0078
WANG_TIME_EXPONENT_Z: float = 0.552

# Thermal Defaults
KELVIN_OFFSET: float = 273.15
DEFAULT_CELL_TEMP_KELVIN: float = 298.15  # 25 degrees Celsius
MAX_CELL_TEMP_CELSIUS: float = 45.0       # Thermal safety cutoff
CRITICAL_THERMAL_RUNAWAY_CELSIUS: float = 190.0

# Electrical and Grid Defaults
DEFAULT_ROUND_TRIP_EFFICIENCY: float = 0.88
MIN_SAFE_SOC: float = 0.15
MAX_SAFE_SOC: float = 0.95
MAX_DAILY_FULL_CYCLES: float = 1.5

# EPDK & EPIAŞ Regulatory Parameters (2025/2026 Revizyonları)
EPDK_TTK_DEVIATION_COEFF_HIGH: float = 0.08
EPDK_TTK_DEVIATION_COEFF_LOW: float = 0.04
TELEMETRY_HEARTBEAT_TIMEOUT_SEC: float = 90.0

# Ecker et al. / Schmalstieg LFP Calendar Aging Constants
ECKER_CALENDAR_EA: float = 22400.0  # J / mol
ECKER_BETA_SOC: float = 0.55         # SoC stress acceleration exponent
ECKER_K_CAL: float = 0.0012          # Pre-exponential calendar factor

# Nature npj Clean Water (2025) Datacenter Water-Energy Nexus
DEFAULT_WATER_LITER_PER_KWH: float = 1.8   # Adiabatic cooling evaporative water consumption
DEFAULT_WATER_COST_TRY_PER_LITER: float = 0.045  # Industrial water tariff TRY / liter

# --- Dynamic GPU Flexibility (rebuttal to arXiv:2609.05406) ---
# The fixed min_gpu_cap=0.65 assumption was refuted: on a 155,410-GPU trace a
# constant-percentage flexibility underestimates real headroom by 17-47%.
# Demand-based bounds replace the constant floor.
GPU_CAP_HARD_FLOOR: float = 0.50        # Never throttle below 50% TDP (hardware/SLA safe limit)
GPU_CAP_CEILING: float = 1.0            # Full TDP
GPU_CAP_LEGACY_DEFAULT: float = 0.65    # Legacy fixed floor, kept only for backward compatibility

# --- Dynamic GPU flexibility *range* (2nd-wave academic rebuttal, 2026) ---
# The fixed min_gpu_cap=0.65 threshold is invalid as a single number:
#
# * arXiv:2609.27926 ("Joule Point") shows energy-per-inference is U-shaped
#   in the power cap and the optimum is *workload-dependent* — it sits at
#   ~43-46% of peak on large GPUs. "high utilization = efficient" is wrong;
#   one fixed cap cannot be optimal for every workload.
# * arXiv:2608.07971 ("ElastiCo") shows static capacity partitions lead to
#   chronic underutilization; the allocation must flex.
# * arXiv:2609.16682 ("DeepShare") shows assurance should be a continuous,
#   demand-driven signal rather than a fixed quota (70.58% utilization,
#   -46% latency vs. static shares).
#
# Hence the floor is now selected *within* a range, per workload:
GPU_CAP_DYNAMIC_MIN: float = 0.35       # Bottom of the dynamic flexibility range (covers the 43-46% optimum)
GPU_CAP_DYNAMIC_MAX: float = 0.95       # Top of the dynamic flexibility range (near-full TDP)

# Queue backlog (pending FLOPS) at/above which the cluster is considered saturated
GPU_FLEX_BACKLOG_SATURATION_FLOPS: float = 500_000.0
# Share of deferred/preemptible workload (Class-1/2/3) that can absorb throttling
GPU_FLEX_MAX_NONCRITICAL_SHARE: float = 0.80
# Elasticity exponent: how sharply demand pressure tightens the cap floor.
# Validated against the 17-47% underestimation band reported in arXiv:2609.05406.
GPU_FLEX_ELASTICITY_EXPONENT: float = 0.85
