from providers.betfair import BetfairProvider

# Forma real de los datos extraídos del DOM de Betfair (ver _EXTRACT_MATCHES_JS),
# capturada en vivo el 2026-09-16 en la página de La Liga.
RAW_MATCHES = [
    {"teams": ["Atlético de Madrid", "Osasuna"], "odds": ["1.34", "5.00", "8.00"]},
    {"teams": ["Solo un equipo"], "odds": ["1.50"]},
]


def test_parses_1x2_from_raw_dom_matches():
    provider = BetfairProvider()
    markets = provider._parse_matches(RAW_MATCHES, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Atlético de Madrid vs. Osasuna"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 1.34), ("X", 5.0), ("2", 8.0)]
    assert all(o.bookmaker == "betfair" for o in market.outcomes)


def test_skips_malformed_matches():
    markets = BetfairProvider()._parse_matches([{"teams": [], "odds": []}], "futbol")
    assert markets == []


# Forma real de los datos extraídos del DOM del mercado fijo "Más/Menos de
# 2,5 Goles" (ver _EXTRACT_OU_MATCHES_JS), capturada en vivo el 2026-09-16.
RAW_OU_MATCHES = [
    {"teams": ["Atlético de Madrid", "Osasuna"], "odds": ["1.72", "2.10"]},
    {"teams": ["Solo un equipo"], "odds": ["1.50"]},
]


def test_parses_over_under_25_from_raw_dom_matches():
    provider = BetfairProvider()
    markets = provider._parse_over_under_matches(RAW_OU_MATCHES, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Atlético de Madrid vs. Osasuna"
    assert market.market_type == "OU_2.5"
    assert [(o.name, o.odds) for o in market.outcomes] == [("Over", 1.72), ("Under", 2.10)]
