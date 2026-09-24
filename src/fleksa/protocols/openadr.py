"""
OpenADR 3.0 / 2.0b Virtual End Node (VEN) Event Handler.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone


class OpenAdrVenHandler:
    """
    Simulates and implements the Virtual End Node (VEN) protocol handling
    for automated demand response (ADR) events from grid operators / aggregators.
    """

    def __init__(self, ven_id: str, facility_max_curtail_kw: float = 250.0):
        self.ven_id = ven_id
        self.max_curtail_kw = facility_max_curtail_kw

    def handle_event(self, event_payload: Dict[str, Any], current_soc_pct: float) -> Dict[str, Any]:
        """
        Processes an incoming OpenADR DistributeEvent message.
        Decides whether to Opt-In or Opt-Out based on facility BESS and workload state.
        """
        event_id = event_payload.get("event_id", "evt-unknown")
        requested_curtail_kw = float(event_payload.get("target_curtail_kw", 0.0))
        duration_seconds = int(event_payload.get("duration_seconds", 3600))

        # Check feasibility: Can facility provide requested curtailment?
        # If battery SoC is too low (<20%), cannot guarantee discharge for the full duration
        if current_soc_pct < 20.0 and requested_curtail_kw > (self.max_curtail_kw * 0.5):
            return {
                "response_type": "OadrCreatedOptEvent",
                "ven_id": self.ven_id,
                "event_id": event_id,
                "opt_type": "OPT_OUT",
                "reason": "INSUFFICIENT_BESS_RESERVE_SOC",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Otherwise accept and Opt-In
        accepted_kw = min(requested_curtail_kw, self.max_curtail_kw)
        return {
            "response_type": "OadrCreatedOptEvent",
            "ven_id": self.ven_id,
            "event_id": event_id,
            "opt_type": "OPT_IN",
            "committed_curtail_kw": accepted_kw,
            "duration_seconds": duration_seconds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
