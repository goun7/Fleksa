"""
Unit tests for Triangulation Canary and Market Feeds.
"""

import pytest
from fleksa.market.canary import TriangulationCanary
from fleksa.market.feeds import EpiasDataParser
from fleksa.core.errors import ByzantinePriceFeedError


def test_triangulation_canary_consensus():
    canary = TriangulationCanary(max_allowed_divergence_pct=35.0)

    # 3 feeds in close agreement around 3500 TL/MWh
    consensus_price = canary.verify_price_quorum(
        epias_price=3450.0,
        teias_price=3520.0,
        regional_proxy_price=3480.0,
    )

    assert 3450.0 <= consensus_price <= 3520.0


def test_triangulation_canary_filters_single_byzantine_outlier():
    canary = TriangulationCanary(max_allowed_divergence_pct=35.0)

    # One feed poisoned (e.g. 10000 TL/MWh due to injection attack)
    consensus_price = canary.verify_price_quorum(
        epias_price=3400.0,
        teias_price=3450.0,
        regional_proxy_price=10000.0,
    )

    # Conforms to the two valid feeds (~3425 TL/MWh)
    assert 3400.0 <= consensus_price <= 3450.0


def test_triangulation_canary_rejects_chaotic_divergence():
    canary = TriangulationCanary(max_allowed_divergence_pct=35.0)

    # All three feeds wildly conflict with no 2-of-3 quorum
    with pytest.raises(ByzantinePriceFeedError, match="Triangulation consensus failed"):
        canary.verify_price_quorum(
            epias_price=1000.0,
            teias_price=4500.0,
            regional_proxy_price=9500.0,
        )


def test_epias_data_parser():
    raw_data = [
        {"date": "2026-09-16T12:00:00Z", "price": 3200.0, "smf": 3500.0, "direction": "ENERGY_DEFICIT"},
        {"date": "2026-09-16T13:00:00Z", "price": 2800.0, "smf": 2600.0, "direction": "ENERGY_SURPLUS"},
    ]

    points = EpiasDataParser.parse_hourly_prices(raw_data)
    assert len(points) == 2
    assert points[0].ptf_try_kwh == 3.20
    assert points[0].smf_try_kwh == 3.50
    assert points[1].ptf_try_kwh == 2.80


def test_economic_arbitrage_gate_theorem_1():
    from fleksa.market.arbitrage_gate import EconomicArbitrageGate

    # Case 1: Profitable Arbitrage (Charge at 1.0 TL, Discharge at 3.5 TL, deg cost 0.35 TL)
    res_profit = EconomicArbitrageGate.evaluate_arbitrage_viability(
        charge_price_try_per_kwh=1.0,
        discharge_price_try_per_kwh=3.5,
        degradation_cost_try_per_kwh=0.35,
        round_trip_efficiency=0.88,
        risk_premium_try=0.05
    )
    assert res_profit["is_viable"] is True
    assert res_profit["verdict"] == "PROFITABLE_ARBITRAGE"
    assert res_profit["net_margin_try_per_kwh"] > 0.0

    # Case 2: Capital Destruction Blocked (Small spread: Charge at 2.0 TL, Discharge at 2.2 TL)
    res_blocked = EconomicArbitrageGate.evaluate_arbitrage_viability(
        charge_price_try_per_kwh=2.0,
        discharge_price_try_per_kwh=2.2,
        degradation_cost_try_per_kwh=0.35,
        round_trip_efficiency=0.88,
        risk_premium_try=0.05
    )
    assert res_blocked["is_viable"] is False
    assert res_blocked["verdict"] == "CAPITAL_DESTRUCTION_BLOCKED"
    assert res_blocked["net_margin_try_per_kwh"] < 0.0
