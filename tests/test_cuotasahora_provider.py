from providers.cuotasahora import (
    _ACCORDION_MARKETS,
    DEFAULT_LEAGUE_URLS,
    HALF_TIME_MARKET_TABS,
    HALF_TIME_SPORT_EXCLUSIONS,
    SPORT_URL_SEGMENT,
    CuotasAhoraProvider,
)

_ACCORDION_SPEC_BY_PREFIX = {spec["market_prefix"]: spec for spec in _ACCORDION_MARKETS}

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

# Pestaña "Resultado sin empate" (DNB), capturada en vivo el 2026-09-16 en
# Real Betis - Getafe (LaLiga).
DNB_TABLE = {
    "headers": ["Bookmakers", "1", "2", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["1.25", "3.70"]},
        {"bookmaker": "bet365", "odds": ["1.25", "3.75"]},
        {"bookmaker": "Sportium.es", "odds": ["1.25", "4.00"]},
    ],
}

# Pestaña "Par/Impar" (OE), misma fuente.
ODD_EVEN_TABLE = {
    "headers": ["Bookmakers", "Odd", "Even", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["1.85", "1.85"]},
        {"bookmaker": "bet365", "odds": ["1.95", "1.90"]},
    ],
}

# Tabla de una línea ya expandida de "Más/Menos de" (goles), capturada en
# vivo el 2026-09-16: incluye la columna "Total" (línea repetida, no una
# cuota) que _parse_over_under_table debe ignorar en vez de tratarla como un
# tercer resultado.
OVER_UNDER_LINE_TABLE = {
    "headers": ["Bookmakers", "Total", "Over", "Under", "Payout"],
    "rows": [
        {"bookmaker": "1xBet.es", "odds": ["+2.5", "2.15", "1.70"]},
        {"bookmaker": "bet365", "odds": ["+2.5", "2.20", "1.67"]},
        {"bookmaker": "Sportium.es", "odds": ["+2.5", "2.10", "1.70"]},
    ],
}

# Tabla de una línea ya expandida de "Hándicap asiático", capturada en vivo
# el 2026-09-17 en Atlético de Madrid - Real Madrid (LaLiga). A diferencia de
# Más/Menos de, aquí el signo de la línea SÍ importa ("-1.5" y "+1.5" son
# mercados distintos), así que no se normaliza al quitarle el "+".
ASIAN_HANDICAP_LINE_TABLE = {
    "headers": ["Bookmakers", "Handicap", "1", "2", "Payout"],
    "rows": [
        {"bookmaker": "1xBet.es", "odds": ["-1.5", "7.00", "1.11"]},
        {"bookmaker": "bet365", "odds": ["-1.5", "6.75", "1.09"]},
        {"bookmaker": "Sportium.es", "odds": ["-1.5", "6.80", "1.10"]},
    ],
}

# Tabla de una línea ya expandida de "Hándicap europeo", misma fuente: línea
# entera con 3 resultados (1/X/2), a diferencia del asiático que no admite
# empate.
EUROPEAN_HANDICAP_LINE_TABLE = {
    "headers": ["Bookmakers", "Handicap", "1", "X", "2", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["-2", "8.00", "17.00", "1.08"]},
        {"bookmaker": "bet365", "odds": ["-2", "8.00", "17.00", "1.10"]},
    ],
}

# Misma tabla 1X2 que ONE_X_TWO_TABLE pero de un partido NBA (baloncesto):
# solo dos resultados (sin empate) - confirma que _parse_match no asume
# fútbol en ningún sitio.
BASKETBALL_MONEYLINE_TABLE = {
    "headers": ["Bookmakers", "1", "2", "Payout"],
    "rows": [
        {"bookmaker": "888sport", "odds": ["1.80", "2.00"]},
        {"bookmaker": "bet365", "odds": ["1.83", "2.00"]},
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


def test_parses_dnb_market_from_headers():
    provider = CuotasAhoraProvider()
    market = provider._parse_match("Real Betis", "Getafe", DNB_TABLE, "DNB", "futbol")

    assert market is not None
    assert market.market_type == "DNB"
    bookmakers = {o.bookmaker for o in market.outcomes}
    assert "sportium" not in bookmakers  # excluida como en el resto de mercados
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 1.25), ("2", 3.75)]


def test_parses_odd_even_market_from_headers():
    provider = CuotasAhoraProvider()
    market = provider._parse_match("Real Betis", "Getafe", ODD_EVEN_TABLE, "OE", "futbol")

    assert market is not None
    assert market.market_type == "OE"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("Odd", 1.95), ("Even", 1.90)]


def test_parses_over_under_line_ignoring_total_column():
    provider = CuotasAhoraProvider()
    spec = _ACCORDION_SPEC_BY_PREFIX["OU"]
    market = provider._parse_accordion_table(
        "Real Betis", "Getafe", OVER_UNDER_LINE_TABLE, "+2.5", "futbol", spec
    )

    assert market is not None
    # La línea se normaliza sin el "+" para casar con la convención de
    # Sportium/Betfair ("OU_2.5"), imprescindible para que group_by_event
    # cruce la misma línea entre proveedores.
    assert market.market_type == "OU_2.5"
    bookmakers = {o.bookmaker for o in market.outcomes}
    assert "sportium" not in bookmakers
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("Over", 2.20), ("Under", 1.67)]


def test_accordion_table_without_matching_headers_returns_none():
    provider = CuotasAhoraProvider()
    spec = _ACCORDION_SPEC_BY_PREFIX["OU"]
    table = {"headers": ["Bookmakers", "Handicap", "Payout"], "rows": []}
    market = provider._parse_accordion_table("A", "B", table, "2.5", "futbol", spec)
    assert market is None


def test_parses_asian_handicap_line_keeping_sign():
    provider = CuotasAhoraProvider()
    spec = _ACCORDION_SPEC_BY_PREFIX["AH"]
    market = provider._parse_accordion_table(
        "Atlético de Madrid", "Real Madrid", ASIAN_HANDICAP_LINE_TABLE, "-1.5", "futbol", spec
    )

    assert market is not None
    # A diferencia de Más/Menos de, el signo de la línea es significativo
    # (favorito vs. no favorito): no se le quita el "-".
    assert market.market_type == "AH_-1.5"
    bookmakers = {o.bookmaker for o in market.outcomes}
    assert "sportium" not in bookmakers
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 6.75), ("2", 1.09)]


def test_parses_european_handicap_line_with_draw():
    provider = CuotasAhoraProvider()
    spec = _ACCORDION_SPEC_BY_PREFIX["EH"]
    market = provider._parse_accordion_table(
        "Atlético de Madrid", "Real Madrid", EUROPEAN_HANDICAP_LINE_TABLE, "-2", "futbol", spec
    )

    assert market is not None
    assert market.market_type == "EH_-2"
    bet365_outcomes = [(o.name, o.odds) for o in market.outcomes if o.bookmaker == "bet365"]
    assert bet365_outcomes == [("1", 8.00), ("X", 17.00), ("2", 1.10)]


def test_parses_basketball_moneyline_without_football_assumptions():
    provider = CuotasAhoraProvider()
    market = provider._parse_match(
        "Boston Celtics", "Detroit Pistons", BASKETBALL_MONEYLINE_TABLE, "1X2", "baloncesto"
    )

    assert market is not None
    assert market.sport == "baloncesto"
    outcome_names = {o.name for o in market.outcomes}
    assert outcome_names == {"1", "2"}  # sin "X": _parse_match no da por hecho que haya empate


def test_parses_baseball_moneyline_without_draw():
    # Misma forma de tabla que baloncesto (sin "X"): confirmado en vivo el
    # 2026-09-17 contra un partido real de MLB (Tampa Bay Rays - Athletics).
    provider = CuotasAhoraProvider()
    market = provider._parse_match(
        "Tampa Bay Rays", "Athletics", BASKETBALL_MONEYLINE_TABLE, "1X2", "beisbol"
    )

    assert market is not None
    assert market.sport == "beisbol"
    outcome_names = {o.name for o in market.outcomes}
    assert outcome_names == {"1", "2"}


def test_sport_url_segment_covers_every_supported_sport():
    assert SPORT_URL_SEGMENT == {
        "futbol": "football",
        "baloncesto": "basketball",
        "tenis": "tennis",
        "balonmano": "handball",
        "beisbol": "baseball",
        "americano": "american-football",
    }


def test_parses_half_time_1x2_reusing_generic_parse_match():
    # Los mercados de 1er tiempo reutilizan _parse_match sin cambios (misma
    # forma de tabla que el partido completo) - _switch_market_tab_with_period
    # solo cambia CÓMO se llega a esa tabla, no cómo se parsea.
    provider = CuotasAhoraProvider()
    market = provider._parse_match(
        "Atlético de Madrid", "Osasuna", ONE_X_TWO_TABLE, HALF_TIME_MARKET_TABS["1X2"], "futbol"
    )
    assert market is not None
    assert market.market_type == "1X2_HT"


def test_half_time_sport_exclusions_skip_basketball_entirely():
    # Baloncesto no ofrece ningún sub-filtro de periodo en la pestaña de
    # resultado (solo dentro del acordeón "Más/Menos de", no implementado
    # aquí) - confirmado en vivo el 2026-09-17. Debe quedar excluido de
    # ambos mercados de 1er tiempo, no solo de uno.
    for market_type in HALF_TIME_MARKET_TABS.values():
        assert "baloncesto" in HALF_TIME_SPORT_EXCLUSIONS.get(market_type, set())


def test_half_time_btts_excluded_for_sports_without_period_or_btts_tab():
    # BTTS_HT solo confirmado en vivo para fútbol: balonmano/béisbol no
    # tienen pestaña BTTS, y fútbol americano sí la tiene pero sin
    # sub-filtro de periodo en ella.
    excluded = HALF_TIME_SPORT_EXCLUSIONS["BTTS_HT"]
    for sport in ("balonmano", "beisbol", "americano"):
        assert sport in excluded
    assert "futbol" not in excluded


def test_every_league_key_derives_a_known_sport():
    # `_fetch_markets_async` deriva el deporte real de cada clave de
    # DEFAULT_LEAGUE_URLS con `sport_key.split("_", 1)[0]` (p.ej.
    # "baloncesto_nba" -> "baloncesto"). Si una clave nueva no sigue esa
    # convención - por ejemplo "futbol_americano_nfl" en vez de
    # "americano_nfl" - el split se rompe en silencio y el deporte nuevo se
    # fusiona por error con el fútbol normal en el motor de arbitraje.
    for league_key in DEFAULT_LEAGUE_URLS:
        sport = league_key.split("_", 1)[0]
        assert sport in SPORT_URL_SEGMENT, f"{league_key!r} deriva el deporte no soportado {sport!r}"
