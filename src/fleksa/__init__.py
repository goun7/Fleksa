"""
Fleksa: Autonomous Energy Flexibility, Distributed BESS Arbitrage
and Grid-Interactive AI Compute Demand Response Engine.
"""

__version__ = "0.1.0"
__author__ = "Fleksa Contributors"

from fleksa.core.types import (
    FacilityState,
    MarketDataHorizon,
    LoadClass,
    BessMode,
    SystemDirection,
    OptimizationResult,
)

__all__ = [
    "FacilityState",
    "MarketDataHorizon",
    "LoadClass",
    "BessMode",
    "SystemDirection",
    "OptimizationResult",
    "__version__",
]
