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
