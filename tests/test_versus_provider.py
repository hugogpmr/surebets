from providers.versus import VersusProvider

# Forma real de los datos extraídos del DOM de Versus (mismo framework "ta-" que
# Sportium/Marca Apuestas, ver _EXTRACT_EVENTS_JS), capturada en vivo el
# 2026-09-24 contra LaLiga (competición id 454900).
RAW_EVENTS = [
    {"teams": ["Málaga", "Espanyol"], "odds": ["2.58", "3.25", "2.72"]},
    {"teams": ["Solo un equipo"], "odds": ["1.50"]},
]


def test_parses_1x2_from_raw_dom_events():
    provider = VersusProvider()
    markets = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Málaga vs. Espanyol"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.58), ("X", 3.25), ("2", 2.72)]
    assert all(o.bookmaker == "versus" for o in market.outcomes)


def test_skips_malformed_events():
    provider = VersusProvider()
    markets = provider._parse_events([{"teams": [], "odds": []}], "futbol")
    assert markets == []


# Forma real del DOM del mercado "Total de Goles" (item del desplegable
# "TotaldeGoles", código interno ta-MarketType-HCTG), capturada en vivo el
# 2026-09-24 - mismo código que Sportium/Marca Apuestas pese al nombre de ítem
# distinto en el desplegable.
RAW_OU_EVENTS = [
    {
        "teams": ["Málaga", "Espanyol"],
        "selections": [{"line": "2.5", "value": "2.00"}, {"line": "2.5", "value": "1.80"}],
    },
]


def test_parses_over_under_with_per_match_line():
    provider = VersusProvider()
    markets = provider._parse_over_under_events(RAW_OU_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.market_type == "OU_2.5"
    assert [(o.name, o.odds) for o in market.outcomes] == [("Over", 2.00), ("Under", 1.80)]


def test_skips_over_under_when_lines_dont_match():
    markets = VersusProvider()._parse_over_under_events(
        [{"teams": ["A", "B"], "selections": [{"line": "2.5", "value": "1.70"}, {"line": "3.5", "value": "2.10"}]}],
        "futbol",
    )
    assert markets == []


# Forma real del DOM de "Ambos Marcan" (ta-item-AmbosMarcan) y "Resultado en el
# descanso" (ta-item-Resultadoeneldescanso), capturada en vivo el 2026-09-24
# (mismos códigos internos BTSC/H1RS que Sportium/Marca Apuestas).
RAW_BTTS_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["1.75", "2.00"]}]
RAW_HT_EVENTS = [{"teams": ["Málaga", "Espanyol"], "odds": ["3.10", "2.10", "3.20"]}]


def test_parses_btts():
    markets = VersusProvider()._parse_simple_market(RAW_BTTS_EVENTS, "futbol", "BTTS", ["Yes", "No"])
    assert markets[0].market_type == "BTTS"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("Yes", 1.75), ("No", 2.00)]


def test_parses_half_time_result():
    markets = VersusProvider()._parse_simple_market(RAW_HT_EVENTS, "futbol", "1X2_HT", ["1", "X", "2"])
    assert markets[0].market_type == "1X2_HT"
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("1", 3.10), ("X", 2.10), ("2", 3.20)]


def test_skips_simple_market_when_outcome_count_does_not_match():
    markets = VersusProvider()._parse_simple_market(
        [{"teams": ["A", "B"], "odds": ["1.80"]}], "futbol", "BTTS", ["Yes", "No"]
    )
    assert markets == []


def test_simple_markets_do_not_include_double_chance_or_handicap():
    # A diferencia de Sportium: sin Doble Oportunidad en el desplegable, y el
    # "Hndicap" de esta casa es de 3 vías con ajuste de marcador (sin pareja en
    # ninguna otra fuente), no el hándicap asiático de 2 vías - ver docstring.
    from providers.versus import SIMPLE_MARKETS

    assert "DobleOportunidad" not in SIMPLE_MARKETS
    assert "Hndicap" not in SIMPLE_MARKETS
