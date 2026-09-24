"""
Market price feeds, EPIAŞ/TEİAŞ data models, and parsers.
"""

from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from fleksa.core.types import SystemDirection


@dataclass
class MarketPricePoint:
    timestamp: datetime
    ptf_try_mwh: float
    smf_try_mwh: float
    system_direction: SystemDirection

    @property
    def ptf_try_kwh(self) -> float:
        return self.ptf_try_mwh / 1000.0

    @property
    def smf_try_kwh(self) -> float:
        return self.smf_try_mwh / 1000.0


class EpiasDataParser:
    """
    Parses EPIAŞ Gün Öncesi Piyasası (GÖP) and Dengeleme Güç Piyasası (DGP) payload responses.
    """

    @staticmethod
    def parse_hourly_prices(raw_items: List[Dict[str, Any]]) -> List[MarketPricePoint]:
        points = []
        for item in raw_items:
            ts_str = item.get("date") or item.get("timestamp")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.utcnow()

            ptf = float(item.get("price", item.get("ptf", 0.0)))
            smf = float(item.get("smf", ptf))
            direction_str = item.get("direction", "BALANCED")

            try:
                direction = SystemDirection(direction_str)
            except ValueError:
                direction = SystemDirection.BALANCED

            points.append(
                MarketPricePoint(
                    timestamp=ts,
                    ptf_try_mwh=ptf,
                    smf_try_mwh=smf,
                    system_direction=direction,
                )
            )
        return points
