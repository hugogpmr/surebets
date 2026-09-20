from engine.matching import best_odds_per_outcome, group_by_event
from engine.models import Market, Outcome


def make_market(event: str, bookmaker: str, odds: dict[str, float]) -> Market:
    outcomes = [Outcome(name=name, bookmaker=bookmaker, odds=o) for name, o in odds.items()]
    return Market(event=event, sport="futbol", market_type="1X2", outcomes=outcomes)


def test_groups_same_event_across_bookmakers_despite_name_variation():
    markets = [
        make_market("Atlético de Madrid vs. Osasuna", "kirolbet", {"1": 1.38, "X": 4.90, "2": 7.50}),
        make_market("At. Madrid vs. Osasuna", "sportium", {"1": 1.35, "X": 4.75, "2": 7.75}),
        make_market("Deportivo vs. Sevilla", "kirolbet", {"1": 2.55, "X": 3.10, "2": 2.95}),
    ]

    groups = group_by_event(markets)

    assert len(groups) == 2
    atm_group = next(g for g in groups if "Osasuna" in g.event)
    assert len(atm_group.outcomes) == 6


def test_does_not_confuse_different_matches_sharing_a_team_name():
    # Bug real detectado en vivo: "Atlético Madrid vs. Osasuna" y "Atlético
    # Madrid vs. Real Madrid" comparten tanto texto ("Atlético", "Madrid")
    # que comparar el string completo del evento los fusionaba como si
    # fueran el mismo partido, aunque el rival es distinto.
    markets = [
        make_market("Atlético Madrid vs. Osasuna", "sportium", {"1": 1.38, "X": 4.90, "2": 7.50}),
        make_market("Atl. Madrid vs. R. Madrid", "winamax", {"1": 3.60, "X": 3.95, "2": 1.80}),
    ]

    groups = group_by_event(markets)

    assert len(groups) == 2


def test_does_not_confuse_teams_sharing_a_common_opponent():
    # Bug real detectado en vivo: "Barcelona vs. Racing S." y "Celta vs.
    # Racing S." comparten el rival, y "Barcelona"/"Celta" resultaron tener
    # suficiente similitud de texto (ratio ~0.57) como para confundirse pese
    # a ser equipos completamente distintos.
    markets = [
        make_market("Barcelona vs. Racing S.", "sportium", {"1": 1.06, "X": 12.0, "2": 26.0}),
        make_market("Celta vs. Racing S.", "sportium", {"1": 1.77, "X": 3.80, "2": 4.20}),
    ]

    groups = group_by_event(markets)

    assert len(groups) == 2


def test_best_odds_per_outcome_keeps_highest_value_per_result():
    combined = make_market("A vs. B", "x", {})
    combined.outcomes = [
        Outcome(name="1", bookmaker="kirolbet", odds=1.38),
        Outcome(name="1", bookmaker="sportium", odds=1.45),
        Outcome(name="X", bookmaker="kirolbet", odds=4.90),
        Outcome(name="X", bookmaker="sportium", odds=4.75),
        Outcome(name="2", bookmaker="kirolbet", odds=7.50),
    ]

    result = best_odds_per_outcome(combined)

    by_name = {o.name: (o.bookmaker, o.odds) for o in result.outcomes}
    assert by_name["1"] == ("sportium", 1.45)
    assert by_name["X"] == ("kirolbet", 4.90)
    assert by_name["2"] == ("kirolbet", 7.50)


def test_same_bookmaker_reported_by_two_providers_keeps_the_lowest_odds():
    # Betway llega por dos proveedores (comparador desfasado + API directa):
    # nos quedamos con la cuota menor para no fabricar una surebet con datos viejos.
    market = Market(
        event="Valencia vs. Real Sociedad",
        sport="futbol",
        market_type="1X2",
        outcomes=[
            Outcome(name="1", bookmaker="betway", odds=2.88),  # comparador, desfasado
            Outcome(name="2", bookmaker="bet365", odds=2.63),
            Outcome(name="1", bookmaker="betway", odds=2.67),  # API directa, fresca
        ],
    )

    result = best_odds_per_outcome(market)

    assert {(o.name, o.bookmaker, o.odds) for o in result.outcomes} == {
        ("1", "betway", 2.67),
        ("2", "bet365", 2.63),
    }


def test_different_bookmakers_still_keep_the_highest_odds_per_result():
    market = Market(
        event="A vs. B",
        sport="futbol",
        market_type="1X2",
        outcomes=[
            Outcome(name="1", bookmaker="bet365", odds=2.0),
            Outcome(name="1", bookmaker="codere", odds=2.2),
        ],
    )

    result = best_odds_per_outcome(market)

    assert [(o.bookmaker, o.odds) for o in result.outcomes] == [("codere", 2.2)]


def test_same_teams_with_very_different_start_times_are_not_merged():
    from datetime import datetime, timedelta, timezone

    first = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
    a = make_market("Ajax vs. Feyenoord", "paf", {"1": 2.0, "X": 3.4, "2": 3.6})
    b = make_market("Ajax vs. Feyenoord", "betway", {"1": 2.1, "X": 3.3, "2": 3.5})
    a.start_time, b.start_time = first, first + timedelta(days=7)
    assert len(group_by_event([a, b])) == 2

    b.start_time = first + timedelta(minutes=30)
    assert len(group_by_event([a, b])) == 1


def test_unknown_start_time_still_merges_by_name_and_adopts_the_known_one():
    from datetime import datetime, timezone

    start = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
    comparator = make_market("Ajax vs. Feyenoord", "bet365", {"1": 2.0, "X": 3.4, "2": 3.6})
    direct = make_market("Ajax vs. Feyenoord", "paf", {"1": 2.1, "X": 3.3, "2": 3.5})
    direct.start_time = start
    (group,) = group_by_event([comparator, direct])
    assert group.start_time == start
    assert best_odds_per_outcome(group).start_time == start
