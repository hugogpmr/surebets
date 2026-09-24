from providers.zebet import ZebetProvider

# Forma real de los datos extraídos del DOM de Zebet (ver _EXTRACT_EVENTS_JS),
# capturada en vivo el 2026-09-24 en la página de competición de LaLiga.
RAW_EVENTS = [
    {"teams": ["Málaga", "Espanyol"], "odds": ["2,50", "3,00", "2,57"]},
    {"teams": ["Real Madrid", "Sevilla"], "odds": ["1,23", "5,30", "7,25"]},
]


def test_parses_1x2_from_raw_dom_events():
    provider = ZebetProvider()
    markets = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(markets) == 2
    market = next(m for m in markets if "Espanyol" in m.event)
    assert market.event == "Málaga vs. Espanyol"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.50), ("X", 3.00), ("2", 2.57)]
    assert all(o.bookmaker == "zebet" for o in market.outcomes)


def test_decimal_comma_is_converted_to_a_point():
    provider = ZebetProvider()
    (market,) = provider._parse_events([{"teams": ["A", "B"], "odds": ["1,23", "5,30", "7,25"]}], "futbol")
    assert [o.odds for o in market.outcomes] == [1.23, 5.30, 7.25]


def test_skips_malformed_or_incomplete_events():
    provider = ZebetProvider()
    cases = [
        {"teams": [], "odds": ["1,50", "3,00", "2,50"]},  # sin ambos equipos
        {"teams": ["A", "B"], "odds": ["1,50", "3,00"]},  # falta una cuota
        {"teams": ["A", "B"], "odds": ["1,50", None, "2,50"]},  # empate suspendido
        {"teams": ["A", "B"], "odds": ["1,00", "3,00", "2,50"]},  # cuota 1.00: no apostable
        {"teams": ["Un solo equipo"], "odds": ["1,50", "3,00", "2,50"]},
    ]
    assert provider._parse_events(cases, "futbol") == []


def test_competition_urls_default_to_laliga():
    provider = ZebetProvider()
    assert provider.competition_urls["futbol"] == "https://www.zebet.es/es/competition/306-laliga"
