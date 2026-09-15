import pytest

from engine.arbitrage import calculate_stakes, evaluate_market, is_surebet, margin
from engine.models import Market, Outcome


def make_market(odds: list[float]) -> Market:
    outcomes = [Outcome(name=str(i), bookmaker=f"casa{i}", odds=o) for i, o in enumerate(odds)]
    return Market(event="Test", sport="futbol", market_type="test", outcomes=outcomes)


def test_detects_surebet_from_doc_example():
    market = make_market([2.00, 2.05])
    assert is_surebet(market)
    assert margin(market) == pytest.approx(0.0122, abs=1e-3)


def test_rejects_non_surebet():
    market = make_market([1.80, 1.80])
    assert not is_surebet(market)


def test_stakes_sum_to_total_and_equalize_profit():
    market = make_market([2.00, 2.05])
    stakes = calculate_stakes(market, 100.0)
    assert sum(stakes.values()) == pytest.approx(100.0, abs=0.05)

    returns = [stake * outcome.odds for stake, outcome in zip(stakes.values(), market.outcomes)]
    assert returns[0] == pytest.approx(returns[1], abs=0.1)


def test_evaluate_market_respects_min_margin():
    market = make_market([1.80, 1.80])
    assert evaluate_market(market, 100.0, min_margin=0.0) is None
