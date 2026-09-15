from providers.kirolbet import KirolbetProvider

# Fragmento real capturado de GET /Api/esp/Lib/Competicion?id=1 (2026-09-15),
# recortado a un solo evento con los dos tipos de mercado soportados.
SAMPLE_RESPONSE = {
    "LstEve": [
        {
            "DesEve": "Atlético de Madrid vs. Osasuna",
            "CodEve": 11775241,
            "Markets": [
                {
                    "DesMod": "1X2",
                    "Pronosticos": [
                        {"DesPro": "1", "CoefCanal": 1.38},
                        {"DesPro": "X", "CoefCanal": 4.90},
                        {"DesPro": "2", "CoefCanal": 7.50},
                    ],
                },
                {
                    "DesMod": "Nº Goles (2,5)",
                    "Pronosticos": [
                        {"DesPro": "- 2,5", "CoefCanal": 2.10},
                        {"DesPro": "+ 2,5", "CoefCanal": 1.70},
                    ],
                },
                {
                    "DesMod": "Otro mercado no soportado",
                    "Pronosticos": [{"DesPro": "Sí", "CoefCanal": 1.50}],
                },
            ],
        }
    ]
}


def test_parses_1x2_and_over_under_markets():
    provider = KirolbetProvider(competition_ids={"futbol": 1})
    markets = provider._parse_events(SAMPLE_RESPONSE, "futbol")

    market_types = {m.market_type for m in markets}
    assert market_types == {"1X2", "OU_2.5"}

    market_1x2 = next(m for m in markets if m.market_type == "1X2")
    assert market_1x2.event == "Atlético de Madrid vs. Osasuna"
    assert [(o.name, o.odds) for o in market_1x2.outcomes] == [("1", 1.38), ("X", 4.90), ("2", 7.50)]
    assert all(o.bookmaker == "kirolbet" for o in market_1x2.outcomes)


def test_ignores_unsupported_market_types():
    provider = KirolbetProvider(competition_ids={"futbol": 1})
    markets = provider._parse_events(SAMPLE_RESPONSE, "futbol")
    assert not any("no soportado" in m.market_type for m in markets)
