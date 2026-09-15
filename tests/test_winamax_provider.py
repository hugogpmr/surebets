from providers.winamax import WinamaxProvider

# Forma real de los datos extraídos del DOM de Winamax (ver _EXTRACT_MATCHES_JS),
# capturada en vivo el 2026-09-16 en la página de LaLiga.
RAW_MATCHES = [
    {
        "outcomes": [
            {"label": "Atl. Madrid", "value": "1,36"},
            {"label": "Empate", "value": "4,90"},
            {"label": "Osasuna", "value": "7,50"},
        ]
    },
    {"outcomes": [{"label": "1", "value": "2.10"}, {"label": "2", "value": "1.70"}]},  # mercado distinto, ignorar
]


def test_parses_1x2_and_converts_comma_decimal():
    markets = WinamaxProvider()._parse_matches(RAW_MATCHES, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Atl. Madrid vs. Osasuna"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 1.36), ("X", 4.9), ("2", 7.5)]
    assert all(o.bookmaker == "winamax" for o in market.outcomes)


def test_skips_non_1x2_markets():
    markets = WinamaxProvider()._parse_matches([RAW_MATCHES[1]], "futbol")
    assert markets == []
