from datetime import datetime, timedelta, timezone

from engine.models import Market, Outcome
from engine.quality import assess, min_outcomes

NOW = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)


def leg(name, bookmaker, odds, source, age_s=0):
    return Outcome(name=name, bookmaker=bookmaker, odds=odds, source=source, fetched_at=NOW - timedelta(seconds=age_s))


def market(outcomes, market_type="OU_2.5", start_in=None):
    return Market(
        event="A vs. B",
        sport="futbol",
        market_type=market_type,
        outcomes=outcomes,
        start_time=NOW + start_in if start_in is not None else None,
    )


def test_direct_sources_are_high_reliability():
    m = market([leg("Over", "betway", 2.2, "altenar"), leg("Under", "paf", 2.1, "kambi")])
    flags, reliability = assess(m, 0.02, NOW)
    assert flags == []
    assert reliability == "alta"


def test_comparator_only_is_low_reliability():
    m = market([leg("Over", "bet365", 2.2, "cuotasahora"), leg("Under", "bwin", 2.1, "betexplorer")])
    flags, reliability = assess(m, 0.02, NOW)
    assert "solo_comparador" in flags
    assert reliability == "baja"


def test_mixed_sources_are_medium_reliability():
    m = market([leg("Over", "bet365", 2.2, "cuotasahora"), leg("Under", "paf", 2.1, "kambi")])
    flags, reliability = assess(m, 0.02, NOW)
    assert flags == []
    assert reliability == "media"


def test_comparator_leg_close_to_kickoff_is_flagged_but_far_away_is_not():
    legs = lambda: [leg("Over", "bet365", 2.2, "cuotasahora"), leg("Under", "paf", 2.1, "kambi")]
    near, reliability = assess(market(legs(), start_in=timedelta(minutes=45)), 0.02, NOW)
    assert "cerca_inicio" in near and reliability == "baja"
    far, _ = assess(market(legs(), start_in=timedelta(hours=10)), 0.02, NOW)
    assert "cerca_inicio" not in far


def test_direct_only_near_kickoff_is_not_penalised():
    m = market([leg("Over", "betway", 2.2, "altenar"), leg("Under", "paf", 2.1, "kambi")], start_in=timedelta(minutes=10))
    flags, reliability = assess(m, 0.02, NOW)
    assert flags == [] and reliability == "alta"


def test_legs_read_far_apart_are_flagged():
    m = market([leg("Over", "bet365", 2.2, "cuotasahora", age_s=1800), leg("Under", "paf", 2.1, "kambi", age_s=5)])
    flags, reliability = assess(m, 0.02, NOW)
    assert "cuotas_desfasadas" in flags and reliability == "baja"


def test_high_margin_warns_and_absurd_margin_blocks():
    m = market([leg("Over", "betway", 3.0, "altenar"), leg("Under", "paf", 3.0, "kambi")])
    warn, reliability = assess(m, 0.08, NOW)
    assert "margen_alto" in warn and reliability == "media"
    blocked, reliability = assess(m, 0.40, NOW)
    assert "margen_absurdo" in blocked and reliability == "baja"


def test_margin_between_15_and_25_is_not_discarded_but_needs_verification():
    m = market([leg("Over", "betway", 3.0, "altenar"), leg("Under", "paf", 3.0, "kambi")])
    flags, reliability = assess(m, 0.20, NOW)
    assert "margen_a_verificar" in flags
    assert not any(f in ("margen_absurdo", "una_sola_casa", "mercado_incompleto") for f in flags)
    assert reliability == "baja"  # sin verificar no se le da fiabilidad


def test_verified_high_margin_keeps_the_reliability_of_its_sources():
    m = market([leg("Over", "betway", 3.0, "altenar"), leg("Under", "paf", 3.0, "kambi")])
    flags, reliability = assess(m, 0.20, NOW, verified=True)
    assert flags == ["margen_verificado"]
    assert reliability == "alta"


def test_margin_above_the_maximum_is_discarded_even_if_verified():
    m = market([leg("Over", "betway", 3.0, "altenar"), leg("Under", "paf", 3.0, "kambi")])
    flags, _ = assess(m, 0.30, NOW, verified=True)
    assert "margen_absurdo" in flags


def test_single_bookmaker_is_blocked():
    m = market([leg("Yes", "bet365", 2.2, "cuotasahora"), leg("No", "bet365", 2.1, "cuotasahora")], "BTTS")
    flags, _ = assess(m, 0.02, NOW)
    assert "una_sola_casa" in flags


def test_market_missing_outcomes_is_blocked():
    # Bug real del estado guardado: un BTTS con una única pata (margen 13 %).
    only_yes = market([leg("Yes", "bet365", 7.0, "cuotasahora")], "BTTS")
    assert "mercado_incompleto" in assess(only_yes, 0.13, NOW)[0]
    # 1X2 al que le falta el empate: parece surebet (1/1.9 + 1/2.6 < 1) sin serlo.
    no_draw = market([leg("1", "a", 1.9, "kambi"), leg("2", "b", 2.6, "altenar")], "1X2")
    assert "mercado_incompleto" in assess(no_draw, 0.09, NOW)[0]


def test_min_outcomes_by_market_family():
    assert min_outcomes("1X2") == min_outcomes("CORNERS_1X2_HT") == min_outcomes("EH_1") == 3
    assert min_outcomes("BTTS") == min_outcomes("OU_2.5") == min_outcomes("AH_-0.5") == min_outcomes("DNB") == 2
