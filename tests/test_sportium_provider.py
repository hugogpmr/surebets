from providers.sportium import SportiumProvider

# Forma real de los datos extraídos del DOM de Sportium (ver _EXTRACT_EVENTS_JS).
RAW_EVENTS = [
    {"teams": ["At. Madrid", "Osasuna"], "odds": ["1.38", "4.75", "7.75", "2.51.70", "2.52.10"]},
    {"teams": ["Solo un equipo"], "odds": ["1.50"]},
]


def test_parses_1x2_from_raw_dom_events():
    provider = SportiumProvider()
    markets = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "At. Madrid vs. Osasuna"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 1.38), ("X", 4.75), ("2", 7.75)]
    assert all(o.bookmaker == "sportium" for o in market.outcomes)


def test_skips_malformed_events():
    provider = SportiumProvider()
    markets = provider._parse_events([{"teams": [], "odds": []}], "futbol")
    assert markets == []


# Forma real de los datos extraídos del DOM del mercado "Goles Totales"
# (ver _EXTRACT_OU_EVENTS_JS), capturada en vivo el 2026-09-16: Sportium
# decide la línea por partido, no siempre es 2.5 (el tercer partido usa 4.5).
RAW_OU_EVENTS = [
    {
        "teams": ["At. Madrid", "Osasuna"],
        "selections": [{"line": "2.5", "value": "1.70"}, {"line": "2.5", "value": "2.10"}],
    },
    {
        "teams": ["Deportivo", "Sevilla"],
        "selections": [{"line": "2.5", "value": "2.20"}, {"line": "2.5", "value": "1.60"}],
    },
    {
        "teams": ["Barcelona", "Racing S."],
        "selections": [{"line": "4.5", "value": "1.75"}, {"line": "4.5", "value": "2.00"}],
    },
]


def test_parses_over_under_with_per_match_line():
    provider = SportiumProvider()
    markets = provider._parse_over_under_events(RAW_OU_EVENTS, "futbol")

    assert len(markets) == 3
    at_madrid = next(m for m in markets if "Osasuna" in m.event)
    assert at_madrid.market_type == "OU_2.5"
    assert [(o.name, o.odds) for o in at_madrid.outcomes] == [("Over", 1.70), ("Under", 2.10)]

    barcelona = next(m for m in markets if "Barcelona" in m.event)
    assert barcelona.market_type == "OU_4.5"


def test_skips_over_under_when_lines_dont_match():
    provider = SportiumProvider()
    markets = provider._parse_over_under_events(
        [{"teams": ["A", "B"], "selections": [{"line": "2.5", "value": "1.70"}, {"line": "3.5", "value": "2.10"}]}],
        "futbol",
    )
    assert markets == []


# Forma real de los datos extraídos del DOM de los mercados "Doble Oportunidad",
# "Ambos Marcan" y "Resultado al descanso" (mismo _EXTRACT_EVENTS_JS que 1X2, ver
# SIMPLE_MARKETS), capturada en vivo el 2026-09-22 contra La Liga.
RAW_DC_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["1.45", "1.33", "1.53"]}]
RAW_BTTS_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["1.80", "1.91"]}]
RAW_HT_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["3.10", "2.20", "3.30"]}]


def test_parses_double_chance():
    markets = SportiumProvider()._parse_simple_market(RAW_DC_EVENTS, "futbol", "DC", ["1X", "12", "X2"])
    assert len(markets) == 1
    assert markets[0].market_type == "DC"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("1X", 1.45), ("12", 1.33), ("X2", 1.53)]


def test_parses_btts():
    markets = SportiumProvider()._parse_simple_market(RAW_BTTS_EVENTS, "futbol", "BTTS", ["Yes", "No"])
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("Yes", 1.80), ("No", 1.91)]


def test_parses_half_time_result():
    markets = SportiumProvider()._parse_simple_market(RAW_HT_EVENTS, "futbol", "1X2_HT", ["1", "X", "2"])
    assert markets[0].market_type == "1X2_HT"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("1", 3.10), ("X", 2.20), ("2", 3.30)]


def test_skips_simple_market_when_outcome_count_does_not_match():
    markets = SportiumProvider()._parse_simple_market(
        [{"teams": ["A", "B"], "odds": ["1.80"]}], "futbol", "BTTS", ["Yes", "No"]
    )
    assert markets == []
