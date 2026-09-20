import pytest

from engine.arbitrage import calculate_stakes, compare_market, evaluate_market, is_surebet, margin
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


def test_guaranteed_profit_matches_equalized_payout():
    # Payout garantizado = total_stake / prob_implicita_total, gane quien
    # gane (ver calculate_stakes). El beneficio debe ser ese payout menos
    # lo invertido, no total_stake * margin sin más: para margenes grandes
    # ambas fórmulas divergen mucho.
    market = make_market([8.0, 5.5])
    comparison = compare_market(market, 250.0)
    total_prob = sum(1 / o.odds for o in market.outcomes)
    expected_profit = round(250.0 * (1 - total_prob) / total_prob, 2)
    assert comparison.guaranteed_profit == pytest.approx(expected_profit)
    for stake, outcome in zip(comparison.stakes.values(), market.outcomes):
        payout = stake * outcome.odds
        assert payout == pytest.approx(250.0 + expected_profit, abs=0.1)


def test_rounded_stakes_are_natural_amounts_and_still_guarantee_profit():
    from engine.arbitrage import round_stakes

    market = make_market([2.10, 2.05])
    result = round_stakes(market, 250.0, step=5.0)
    assert result is not None
    stakes, profit = result
    assert all(amount % 5 == 0 for amount in stakes.values())
    total = sum(stakes.values())
    # el beneficio devuelto es el peor caso real con los importes redondeados
    worst = min(stake * o.odds for stake, o in zip(stakes.values(), market.outcomes)) - total
    assert profit == pytest.approx(worst, abs=0.01)
    assert profit > 0


def test_rounding_falls_back_to_one_euro_steps_or_none_for_thin_surebets():
    from engine.arbitrage import round_stakes

    thin = make_market([2.00, 2.03])  # margen ~0,7 %
    result = round_stakes(thin, 40.0, step=10.0)
    assert result is None or result[1] > 0  # nunca devuelve un reparto que pierda dinero
    assert round_stakes(make_market([2.10, 2.05]), 250.0, step=0) is None


def test_compare_market_only_rounds_when_asked():
    market = make_market([2.10, 2.05])
    assert compare_market(market, 250.0).rounded_stakes is None
    rounded = compare_market(market, 250.0, round_step=5.0)
    assert rounded.rounded_stakes is not None and rounded.rounded_profit > 0
