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
