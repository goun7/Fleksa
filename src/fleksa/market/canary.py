"""
Triangulation Canary: Multi-source Byzantine price feed verification and quorum validation.
"""

from typing import Dict, Any, List
import numpy as np

from fleksa.core.errors import ByzantinePriceFeedError


class TriangulationCanary:
    """
    Validates electricity price signals against 3 independent feeds:
    1. EPIAŞ Primary Market API
    2. TEİAŞ Secondary SMF/Load Telemetry
    3. Regional/ENTSO-E Trend Corroborator
    
    Prevents price-poisoning attacks and false demand response triggers.
    """

    def __init__(self, max_allowed_divergence_pct: float = 35.0):
        self.max_divergence = max_allowed_divergence_pct

    def verify_price_quorum(
        self,
        epias_price: float,
        teias_price: float,
        regional_proxy_price: float,
    ) -> float:
        """
        Computes 2-of-3 quorum consensus.
        Returns accepted median price or raises ByzantinePriceFeedError.
        """
        prices = [float(epias_price), float(teias_price), float(regional_proxy_price)]

        # Check for negative or implausible values
        for p in prices:
            if p < -500.0 or p > 15000.0:  # Beyond reasonable bounds in TL/MWh
                raise ByzantinePriceFeedError(f"Implausible price outlier detected: {p} TL/MWh")

        median_val = float(np.median(prices))

        # Check pairwise deviations from median
        divergences = [abs(p - median_val) / max(100.0, median_val) * 100.0 for p in prices]

        # At least 2 feeds must be within max_divergence of the median
        valid_feeds_count = sum(1 for d in divergences if d <= self.max_divergence)

        if valid_feeds_count < 2:
            raise ByzantinePriceFeedError(
                f"Triangulation consensus failed: Prices {prices} exhibit excessive divergence ({divergences}%)."
            )

        # Return consensus price (average of the conforming feeds)
        conforming_prices = [p for p, d in zip(prices, divergences) if d <= self.max_divergence]
        return float(np.mean(conforming_prices))
