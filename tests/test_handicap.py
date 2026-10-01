from datetime import datetime, timezone

from engine.handicap import ASIAN, EUROPEAN, UNKNOWN, check_whole_handicaps, whole_line
from engine.models import Market, Outcome
from engine.scan import _build_comparisons, format_alert

EVENT = "Gales vs. Noruega"


def ah(line: str, *legs: tuple[str, str, float]) -> Market:
    return Market(
        event=EVENT,
        sport="futbol",
        market_type=f"AH_{line}",
        outcomes=[Outcome(name=name, bookmaker=book, odds=odds, source="altenar") for book, name, odds in legs],
    )


def test_whole_line():
    assert whole_line("AH_-1") == ("AH", -1.0)
    assert whole_line("AH_HT_+2") == ("AH_HT", 2.0)
    assert whole_line("CORNERS_AH_0") == ("CORNERS_AH", 0.0)
    assert whole_line("AH_-1.5") is None
    assert whole_line("AH_-0.5/-1") is None
    assert whole_line("OU_2") is None


def test_both_sides_summing_below_one_is_three_way_and_dropped():
    # Caso real 2026-09-30: 888sport/Betfair daban el europeo sin "Empate" (suma ~0,8).
    market = ah("1", ("888sport", "1", 1.75), ("888sport", "2", 4.33), ("bet365", "2", 2.10))
    groups, verdicts, dropped = check_whole_handicaps([market])
    assert dropped == 2
    assert [o.bookmaker for o in groups[0].outcomes] == ["bet365"]
    assert verdicts[id(groups[0])] == {"bet365": UNKNOWN}


def test_both_sides_with_margin_is_asian():
    market = ah("-1", ("bet777", "1", 1.95), ("bet777", "2", 1.85))
    groups, verdicts, dropped = check_whole_handicaps([market])
    assert dropped == 0
    assert verdicts[id(groups[0])] == {"bet777": ASIAN}


def ladder(book: str, odds_minus_1: float) -> list[Market]:
    # Gana por 2+: 1/3.00; gana por 1+: 1/1.50 -> asiático -1 justo ~2.00, europeo ~3.00.
    return [
        ah("-0.5", (book, "1", 1.50)),
        ah("-1", (book, "1", odds_minus_1)),
        ah("-1.5", (book, "1", 3.00)),
    ]


def test_single_side_judged_by_its_ladder():
    groups, verdicts, dropped = check_whole_handicaps(ladder("jokerbet", 1.95))
    assert dropped == 0
    assert verdicts[id(groups[1])] == {"jokerbet": ASIAN}

    groups, verdicts, dropped = check_whole_handicaps(ladder("jokerbet", 2.90))
    assert dropped == 1
    assert groups[1].outcomes == []


def test_alert_says_whether_the_handicap_was_checked():
    now = datetime.now(timezone.utc)
    markets = [
        ah("1", ("bet777", "1", 2.20), ("bet777", "2", 1.70)),
        ah("1", ("jokerbet", "1", 1.60), ("jokerbet", "2", 2.40)),
    ]
    args = (100.0, 0.0, 0.0, now, 0.05, 0.10, 0.25)
    comparisons = [c for c in _build_comparisons(markets, *args) if c.is_surebet]
    assert len(comparisons) == 1
    text = format_alert(comparisons[0])
    assert "✅ Comprobado con las cuotas de cada casa que es hándicap asiático" in text
    assert "Si Noruega acaba exactamente 1 gol por delante, se devuelven las dos apuestas" in text

    markets = [ah("1", ("bet777", "1", 2.20)), ah("1", ("jokerbet", "2", 2.40))]
    comparisons = [c for c in _build_comparisons(markets, *args) if c.is_surebet]
    text = format_alert(comparisons[0])
    assert "handicap_sin_comprobar" in comparisons[0].flags
    assert "NO tenga opción de «Empate»" in text


def test_three_way_leg_never_makes_a_surebet():
    now = datetime.now(timezone.utc)
    markets = [
        ah("1", ("888sport", "1", 1.75), ("888sport", "2", 4.33)),
        ah("1", ("bet365", "1", 1.50), ("bet365", "2", 2.50)),
    ]
    comparisons = _build_comparisons(markets, 100.0, 0.0, 0.0, now, 0.05, 0.10, 0.25)
    assert not any(c.is_surebet for c in comparisons)
