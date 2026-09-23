from providers.marcaapuestas import MarcaApuestasProvider

# Forma real de los datos extraídos del DOM de Marca Apuestas (mismo framework
# "ta-" que Sportium, ver _EXTRACT_EVENTS_JS), capturada en vivo el 2026-09-23
# contra Primera División (competición id 19160).
RAW_EVENTS = [
    {"teams": ["Málaga", "Espanyol"], "odds": ["2.56", "3.25", "2.70"]},
    {"teams": ["Solo un equipo"], "odds": ["1.50"]},
]


def test_parses_1x2_from_raw_dom_events():
    provider = MarcaApuestasProvider()
    markets = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Málaga vs. Espanyol"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.56), ("X", 3.25), ("2", 2.70)]
    assert all(o.bookmaker == "marcaapuestas" for o in market.outcomes)


def test_skips_malformed_events():
    provider = MarcaApuestasProvider()
    markets = provider._parse_events([{"teams": [], "odds": []}], "futbol")
    assert markets == []


# Forma real del DOM del mercado "Goles Totales", capturada en vivo el 2026-09-23.
RAW_OU_EVENTS = [
    {
        "teams": ["Málaga", "Espanyol"],
        "selections": [{"line": "2.5", "value": "2.00"}, {"line": "2.5", "value": "1.80"}],
    },
]


def test_parses_over_under_with_per_match_line():
    provider = MarcaApuestasProvider()
    markets = provider._parse_over_under_events(RAW_OU_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.market_type == "OU_2.5"
    assert [(o.name, o.odds) for o in market.outcomes] == [("Over", 2.00), ("Under", 1.80)]


def test_skips_over_under_when_lines_dont_match():
    markets = MarcaApuestasProvider()._parse_over_under_events(
        [{"teams": ["A", "B"], "selections": [{"line": "2.5", "value": "1.70"}, {"line": "3.5", "value": "2.10"}]}],
        "futbol",
    )
    assert markets == []


# Forma real del DOM de "Ambos Marcan" y "Resultado al descanso", capturada en
# vivo el 2026-09-23 (mismos códigos internos BTSC/H1RS que Sportium).
RAW_BTTS_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["1.75", "2.00"]}]
RAW_HT_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["3.10", "2.10", "3.20"]}]


def test_parses_btts():
    markets = MarcaApuestasProvider()._parse_simple_market(RAW_BTTS_EVENTS, "futbol", "BTTS", ["Yes", "No"])
    assert markets[0].market_type == "BTTS"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("Yes", 1.75), ("No", 2.00)]


def test_parses_half_time_result():
    markets = MarcaApuestasProvider()._parse_simple_market(RAW_HT_EVENTS, "futbol", "1X2_HT", ["1", "X", "2"])
    assert markets[0].market_type == "1X2_HT"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("1", 3.10), ("X", 2.10), ("2", 3.20)]


def test_skips_simple_market_when_outcome_count_does_not_match():
    markets = MarcaApuestasProvider()._parse_simple_market(
        [{"teams": ["A", "B"], "odds": ["1.80"]}], "futbol", "BTTS", ["Yes", "No"]
    )
    assert markets == []
