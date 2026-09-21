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


def _refs(*markets):
    from engine.matching import event_key
    from engine.quality import _canonical_type

    refs = {}
    for m in markets:
        refs.setdefault((m.sport, event_key(m.event)), []).append(
            (_canonical_type(m.market_type), frozenset((o.bookmaker, o.odds) for o in m.outcomes))
        )
    return refs


def _key(m):
    from engine.matching import event_key

    return (m.sport, event_key(m.event))


def test_table_of_another_tab_read_twice_is_detected():
    from engine.quality import find_mirrored

    one_x_two = market(
        [leg("1", "bet365", 2.55, "cuotasahora"), leg("X", "versus", 3.85, "cuotasahora"), leg("2", "paf", 2.63, "cuotasahora")],
        "1X2",
    )
    # BTTS con las cuotas 1 y X del 1X2: la lectura de la pestaña BTTS ensenaba aun el 1X2
    btts = market([leg("Yes", "bet365", 2.55, "cuotasahora"), leg("No", "versus", 3.85, "cuotasahora")], "BTTS")
    refs = _refs(one_x_two, btts)
    assert find_mirrored([(btts, _key(btts))], refs) == {0}
    # el propio 1X2 (tabla original) nunca se marca
    assert find_mirrored([(one_x_two, _key(one_x_two))], refs) == set()


def test_genuinely_different_odds_are_not_flagged():
    from engine.quality import find_mirrored

    one_x_two = market([leg("1", "bet365", 2.55, "cuotasahora"), leg("X", "versus", 3.85, "cuotasahora"), leg("2", "paf", 2.63, "cuotasahora")], "1X2")
    btts = market([leg("Yes", "bet365", 2.4, "cuotasahora"), leg("No", "versus", 3.85, "cuotasahora")], "BTTS")
    assert find_mirrored([(btts, _key(btts))], _refs(one_x_two, btts)) == set()


def test_asian_handicap_zero_and_draw_no_bet_are_the_same_market_not_a_mirror():
    from engine.quality import find_mirrored

    dnb = market([leg("1", "bet365", 2.5, "cuotasahora"), leg("2", "paf", 2.5, "cuotasahora")], "DNB")
    ah0 = market([leg("1", "bet365", 2.5, "cuotasahora"), leg("2", "paf", 2.5, "cuotasahora")], "AH_0")
    assert find_mirrored([(ah0, _key(ah0))], _refs(dnb, ah0)) == set()


def test_mixed_candidate_whose_comparator_leg_is_the_full_time_price_is_detected():
    from engine.quality import find_mirrored

    # 1X2 del partido completo: el comparador tiene la X de bet365 a 3.6
    full_time = market([leg("1", "bet365", 2.4, "cuotasahora"), leg("X", "bet365", 3.6, "cuotasahora"), leg("2", "bet365", 2.9, "cuotasahora")], "1X2")
    # "1X2_HT": patas 1 y 2 directas de Winamax (al descanso) + una X de bet365 que en realidad es la del final
    half_time = market([leg("1", "winamax", 2.5, "winamax"), leg("X", "bet365", 3.6, "cuotasahora"), leg("2", "winamax", 3.75, "winamax")], "1X2_HT")
    assert find_mirrored([(half_time, _key(half_time))], _refs(full_time, half_time)) == {0}

    # con una X genuinamente distinta no se marca
    real_half_time = market([leg("1", "winamax", 2.5, "winamax"), leg("X", "bet365", 2.2, "cuotasahora"), leg("2", "winamax", 3.75, "winamax")], "1X2_HT")
    assert find_mirrored([(real_half_time, _key(real_half_time))], _refs(full_time, real_half_time)) == set()


# --- cuotas atípicas frente a la mediana de las demás casas -----------------------------------------------------


def book(name, odds, bookmaker, source="cuotasahora"):
    return Outcome(name=name, bookmaker=bookmaker, odds=odds, source=source, fetched_at=NOW)


def test_a_leg_far_from_the_median_of_the_other_books_is_an_outlier():
    from engine.quality import leg_outliers

    # caso real: Betway pagando 16,0 al "2" cuando las otras 10 casas rondan 2,1
    others = [book("2", odds, f"casa{i}") for i, odds in enumerate([2.05, 2.1, 2.14, 2.2, 2.1, 2.16])]
    betway = book("2", 16.0, "betway")
    assert leg_outliers(others + [betway], [betway]) == [betway]


def test_normal_dispersion_and_long_shots_are_not_outliers():
    from engine.quality import leg_outliers

    close = [book("Over", o, f"casa{i}") for i, o in enumerate([1.9, 1.92, 1.95, 1.88])]
    best = book("Over", 2.0, "otra")  # 5 % por encima: una surebet real se ve así
    assert leg_outliers(close + [best], [best]) == []
    # ratio 1,5 pero solo 3 puntos de probabilidad: resultado improbable, no un error
    long_shots = [book("Under", o, f"casa{i}") for i, o in enumerate([10.0, 10.0, 9.5, 10.5])]
    shot = book("Under", 15.0, "otra")
    assert leg_outliers(long_shots + [shot], [shot]) == []


def test_outliers_need_at_least_two_other_books_and_the_leg_is_not_its_own_reference():
    from engine.quality import leg_outliers

    one_other = [book("Yes", 1.3, "a")]
    leg = book("Yes", 2.5, "c")
    assert leg_outliers(one_other + [leg], [leg]) == []  # sin referencia suficiente no se juzga
    two_others = one_other + [book("Yes", 1.32, "b")]
    assert leg_outliers(two_others + [leg], [leg]) == [leg]


def test_comparator_outliers_invalidate_but_direct_ones_only_warn():
    from engine.quality import leg_flags

    others = [book("No", o, f"casa{i}") for i, o in enumerate([1.3, 1.32, 1.31, 1.29])]
    bad_comparator = book("No", 2.22, "retabet", "cuotasahora")
    bad_direct = book("No", 2.22, "leovegas", "kambi")
    assert leg_flags(others + [bad_comparator], [bad_comparator]) == ["cuota_atipica"]
    assert leg_flags(others + [bad_direct], [bad_direct]) == ["cuota_destacada"]
    assert leg_flags(others, [others[0]]) == []


# --- filas de comparador imposibles (suma de probabilidades < 1) ------------------------------------------------


def row(bookmaker, yes, no, source="cuotasahora"):
    return [book("Yes", yes, bookmaker, source), book("No", no, bookmaker, source)]


def test_rows_that_sum_below_one_are_dropped_and_the_rest_kept():
    from engine.quality import drop_incoherent_rows

    m = Market("A vs. B", "futbol", "BTTS_HT", row("bet365", 3.25, 2.2) + row("paf", 4.5, 1.2) + row("888sport", 4.2, 1.22))
    cleaned, dropped = drop_incoherent_rows(m)
    assert dropped == 1 and {o.bookmaker for o in cleaned.outcomes} == {"paf", "888sport"}
    assert cleaned.start_time == m.start_time and cleaned.market_type == "BTTS_HT"


def test_coherent_markets_direct_rows_and_double_chance_are_never_touched():
    from engine.quality import drop_incoherent_rows

    normal = Market("A vs. B", "futbol", "BTTS", row("bet365", 1.9, 1.95) + row("paf", 1.85, 2.0))
    assert drop_incoherent_rows(normal) == (normal, 0)
    # una fila DIRECTA por debajo de 1 sería un error real de la casa, no de lectura
    direct = Market("A vs. B", "futbol", "BTTS", row("leovegas", 2.2, 2.2, "kambi") + row("paf", 1.85, 2.0))
    assert drop_incoherent_rows(direct)[1] == 0
    # doble oportunidad: los resultados se solapan y suman ~2, no es un mercado exhaustivo
    dc = Market("A vs. B", "futbol", "DC", [book("1X", 1.3, "a"), book("12", 1.25, "a"), book("X2", 1.6, "a")])
    assert drop_incoherent_rows(dc)[1] == 0


def test_rows_that_do_not_give_every_outcome_are_not_judged():
    from engine.quality import drop_incoherent_rows

    m = Market("A vs. B", "futbol", "BTTS", [book("Yes", 3.0, "solo_yes")] + row("bet365", 1.9, 1.95))
    assert drop_incoherent_rows(m)[1] == 0
