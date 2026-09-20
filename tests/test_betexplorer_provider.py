from providers.betexplorer import DEFAULT_LEAGUE_URLS, BetExplorerProvider

ONE_X_TWO_TABLE = {
    "headers": ["1", "X", "2"],
    "rows": [
        ["1xBet.es", "1.86", "3.52", "4.36"],
        ["bet365", "1.83", "3.50", "4.50"],
        ["Sportium.es", "1.87", "3.65", "4.33"],
    ],
}

DNB_TABLE = {
    "headers": ["1", "2"],
    "rows": [
        ["888sport", "1.25", "3.70"],
        ["bet365", "1.25", "3.75"],
    ],
}

DC_TABLE = {
    "headers": ["1X", "12", "X2"],
    "rows": [
        ["888sport", "3.10", "1.15", "1.10"],
        ["bet365", "3.40", "1.14", "1.08"],
    ],
}

BTTS_TABLE = {
    "headers": ["Yes", "No"],
    "rows": [
        ["888sport", "1.44", "2.75"],
        ["bet365", "1.50", "2.50"],
    ],
}

OU_LINE_TABLE = {
    "headers": ["Total", "Over", "Under"],
    "rows": [
        ["1xBet.es", "2.5", "1.84", "1.96"],
        ["bet365", "2.5", "1.80", "2.00"],
    ],
}

OU_SPLIT_LINE_TABLE = {
    "headers": ["Total", "Over", "Under"],
    "rows": [
        ["1xBet.es", "2, 2.5", "1.70", "2.10"],
    ],
}


def test_parses_1x2_market_and_excludes_sportium():
    provider = BetExplorerProvider()
    market = provider._parse_flat_table("Espanyol", "Elche", ONE_X_TWO_TABLE, "1X2", "futbol")

    assert market is not None
    assert market.event == "Espanyol vs. Elche"
    assert market.market_type == "1X2"
    bookmakers = {o.bookmaker for o in market.outcomes}
    assert "sportium" not in bookmakers
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 1.83), ("X", 3.50), ("2", 4.50)]


def test_parses_dnb_market():
    provider = BetExplorerProvider()
    market = provider._parse_flat_table("Real Betis", "Getafe", DNB_TABLE, "DNB", "futbol")

    assert market is not None
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 1.25), ("2", 3.75)]


def test_parses_double_chance_market():
    provider = BetExplorerProvider()
    market = provider._parse_flat_table("Galatasaray", "Barcelona", DC_TABLE, "DC", "futbol")

    assert market is not None
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1X", 3.40), ("12", 1.14), ("X2", 1.08)]


def test_parses_both_teams_to_score_market():
    provider = BetExplorerProvider()
    market = provider._parse_flat_table("Galatasaray", "Barcelona", BTTS_TABLE, "BTTS", "futbol")

    assert market is not None
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("Yes", 1.50), ("No", 2.50)]


def test_flat_table_without_allowed_bookmakers_returns_none():
    table = {"headers": ["1", "X", "2"], "rows": [["Sportium.es", "1.80", "3.50", "4.50"]]}
    provider = BetExplorerProvider()
    assert provider._parse_flat_table("A", "B", table, "1X2", "futbol") is None


def test_parses_over_under_line_keeping_total_as_line():
    provider = BetExplorerProvider()
    market = provider._parse_line_table("Espanyol", "Elche", OU_LINE_TABLE, "futbol", "OU")

    assert market is not None
    assert market.market_type == "OU_2.5"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("Over", 1.80), ("Under", 2.00)]


def test_parses_split_handicap_line_without_commas_or_spaces():
    provider = BetExplorerProvider()
    market = provider._parse_line_table("Espanyol", "Elche", OU_SPLIT_LINE_TABLE, "futbol", "OU")

    assert market is not None
    assert market.market_type == "OU_2/2.5"


def test_parses_asian_handicap_line_keeping_negative_sign():
    table = {
        "headers": ["Handicap", "1", "2"],
        "rows": [["1xBet.es", "-2, -2.5", "5.98", "1.07"], ["bet365", "-2, -2.5", "6.00", "1.08"]],
    }
    provider = BetExplorerProvider()
    market = provider._parse_line_table("Espanyol", "Elche", table, "futbol", "AH")

    assert market is not None
    assert market.market_type == "AH_-2/-2.5"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 6.00), ("2", 1.08)]


def test_line_table_ignores_rows_with_a_different_line():
    table = {
        "headers": ["Total", "Over", "Under"],
        "rows": [["bet365", "2.5", "1.80", "2.00"], ["codere", "3.5", "3.00", "1.30"]],
    }
    provider = BetExplorerProvider()
    market = provider._parse_line_table("A", "B", table, "futbol", "OU")

    assert market is not None
    assert market.market_type == "OU_2.5"
    assert {o.bookmaker for o in market.outcomes} == {"bet365"}


def test_line_table_without_total_or_handicap_header_returns_none():
    table = {"headers": ["Foo", "Over", "Under"], "rows": [["bet365", "2.5", "1.80", "2.00"]]}
    provider = BetExplorerProvider()
    assert provider._parse_line_table("A", "B", table, "futbol", "OU") is None


def test_default_league_urls_are_betexplorer_com():
    for url in DEFAULT_LEAGUE_URLS.values():
        assert url.startswith("https://www.betexplorer.com/")
