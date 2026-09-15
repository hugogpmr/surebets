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
