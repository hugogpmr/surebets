from providers.cuotasahora import CuotasAhoraProvider

# Forma real de los datos extraídos de la tabla de casas de cuotasahora.com
# (ver _EXTRACT_ODDS_TABLE_JS), capturada en vivo el 2026-09-16 en la página
# de Atlético de Madrid - Osasuna (pestaña 1X2).
ONE_X_TWO_TABLE = {
    "headers": ["Bookmakers", "1", "X", "2", "Payout"],
    "rows": [
        {"bookmaker": "1xBet.es", "odds": ["1.38", "4.84", "8.40"]},  # DGOJ verificado (WAGERFAIR, S.A.)
        {"bookmaker": "888sport", "odds": ["1.40", "4.50", "7.50"]},
        {"bookmaker": "bet365", "odds": ["1.38", "4.75", "8.50"]},
        {"bookmaker": "Betway", "odds": ["1.38", "4.75", "8.00"]},
        {"bookmaker": "bwin.es", "odds": ["1.39", "4.80", "7.75"]},
        {"bookmaker": "Codere", "odds": ["1.43", "4.25", "6.75"]},
        {"bookmaker": "Luckia.es", "odds": ["1.38", "5.00", "7.90"]},
        {"bookmaker": "Paf.es", "odds": ["1.35", "5.00", "8.50"]},
        {"bookmaker": "Retabet", "odds": ["1.38", "5.15", "8.10"]},
        {"bookmaker": "Speedybet.es", "odds": ["1.35", "5.00", "8.50"]},
        # Sportium/Winamax aparecen en la web pero se excluyen a propósito:
        # ya los scrapeamos en directo, no vía comparador.
        {"bookmaker": "Sportium.es", "odds": ["1.38", "5.00", "8.50"]},
        {"bookmaker": "Versus.es", "odds": ["1.39", "4.60", "8.90"]},
        {"bookmaker": "William Hill", "odds": ["1.40", "4.50", "7.50"]},
        {"bookmaker": "Winamax.es", "odds": ["1.36", "4.90", "7.50"]},
    ],
}

# Pestaña "Ambos equipos marcan" (BTTS), capturada en vivo el 2026-09-16 en
# Galatasaray - Barcelona (Champions League).
BTTS_TABLE = {
    "headers": ["Bookmakers", "Yes", "No", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["1.44", "2.75"]},
        {"bookmaker": "bet365", "odds": ["1.50", "2.50"]},
        {"bookmaker": "Betway", "odds": ["1.44", "2.63"]},
    ],
}

# Pestaña "Doble oportunidad", misma fuente que BTTS.
DOUBLE_CHANCE_TABLE = {
    "headers": ["Bookmakers", "1X", "12", "X2", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["3.10", "1.15", "1.10"]},
        {"bookmaker": "bet365", "odds": ["3.40", "1.14", "1.08"]},
        {"bookmaker": "Betway", "odds": ["3.00", "1.14", "1.11"]},
    ],
}


def test_parses_only_allowed_bookmakers():
    provider = CuotasAhoraProvider()
    market = provider._parse_match("Atlético de Madrid", "Osasuna", ONE_X_TWO_TABLE, "1X2", "futbol")

    assert market is not None
    assert market.event == "Atlético de Madrid vs. Osasuna"
    assert market.market_type == "1X2"

    bookmakers = {o.bookmaker for o in market.outcomes}
    assert bookmakers == {
        "1xbet", "888sport", "bet365", "betway", "bwin", "codere", "luckia",
        "paf", "retabet", "speedybet", "versus", "williamhill",
    }
    # Sportium/Winamax se excluyen porque ya los scrapeamos en directo (no por licencia)
    assert "sportium" not in bookmakers
    assert "winamax" not in bookmakers

    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 1.38), ("X", 4.75), ("2", 8.50)]


def test_returns_none_when_no_allowed_bookmaker_present():
    provider = CuotasAhoraProvider()
    table = {"headers": ["Bookmakers", "1", "X", "2", "Payout"], "rows": [{"bookmaker": "Sportium.es", "odds": ["1.5", "2.5", "3.5"]}]}
    market = provider._parse_match("A", "B", table, "1X2", "futbol")
    assert market is None


def test_parses_btts_market_from_headers():
    provider = CuotasAhoraProvider()
    market = provider._parse_match("Galatasaray", "Barcelona", BTTS_TABLE, "BTTS", "futbol")

    assert market is not None
    assert market.market_type == "BTTS"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("Yes", 1.50), ("No", 2.50)]


def test_parses_double_chance_market_from_headers():
    provider = CuotasAhoraProvider()
    market = provider._parse_match("Galatasaray", "Barcelona", DOUBLE_CHANCE_TABLE, "DC", "futbol")

    assert market is not None
    assert market.market_type == "DC"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1X", 3.40), ("12", 1.14), ("X2", 1.08)]


def test_returns_none_when_no_outcome_headers():
    provider = CuotasAhoraProvider()
    table = {"headers": ["Bookmakers", "Payout"], "rows": [{"bookmaker": "bet365", "odds": []}]}
    market = provider._parse_match("A", "B", table, "1X2", "futbol")
    assert market is None
