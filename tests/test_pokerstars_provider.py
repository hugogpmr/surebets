from providers.pokerstars import PokerStarsProvider, _parse_odds

# Forma real de los datos que devuelve _EXTRACT_JS (ver providers/pokerstars.py),
# capturada a mano en vivo el 2026-09-22 contra /sports/futbol/1/matches/: cada
# bloque de competición trae su cabecera de mercado ("...LocalEmpateVisitante"
# para 1X2) y su lista de eventos con las cuotas en coma decimal española.
RAW_GROUPS = [
    {
        "heading": "Primera B Colombiana",
        "marketHeader": "Resultado del partidoLocalEmpateVisitante",
        "events": [
            {"home": "Real Santander", "away": "Orsomarso", "odds": ["2,90", "2,20", "3,20"]},
        ],
    }
]


def test_parses_1x2_from_raw_dom_groups():
    provider = PokerStarsProvider()
    markets = provider._parse_groups(RAW_GROUPS)

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Real Santander vs. Orsomarso"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.90), ("X", 2.20), ("2", 3.20)]
    assert all(o.bookmaker == "pokerstars" for o in market.outcomes)


def test_skips_group_whose_market_is_not_1x2():
    provider = PokerStarsProvider()
    groups = [
        {
            "heading": "Alguna liga",
            "marketHeader": "Total de golesMás deMenos de",
            "events": [{"home": "A", "away": "B", "odds": ["1,90", "1,90"]}],
        }
    ]
    assert provider._parse_groups(groups) == []


def test_skips_event_with_wrong_outcome_count():
    provider = PokerStarsProvider()
    groups = [
        {
            "heading": "Liga",
            "marketHeader": "Cuotas de partidoLocalEmpateVisitante",
            "events": [{"home": "A", "away": "B", "odds": ["1,90", "2,00"]}],
        }
    ]
    assert provider._parse_groups(groups) == []


def test_skips_event_with_suspended_selection():
    provider = PokerStarsProvider()
    groups = [
        {
            "heading": "Liga",
            "marketHeader": "Cuotas de partidoLocalEmpateVisitante",
            "events": [{"home": "A", "away": "B", "odds": ["1,90", "-", "4,00"]}],
        }
    ]
    assert provider._parse_groups(groups) == []


def test_excludes_womens_football_by_default():
    provider = PokerStarsProvider()
    groups = [
        {
            "heading": "Champions League Femenina",
            "marketHeader": "Cuotas de partidoLocalEmpateVisitante",
            "events": [{"home": "FC Barcelona Femenino", "away": "Paris FC Femenino", "odds": ["1,01", "23,00", "61,00"]}],
        }
    ]
    assert provider._parse_groups(groups) == []


def test_parse_odds_converts_spanish_decimal_comma():
    assert _parse_odds("2,30") == 2.30
    assert _parse_odds("61,00") == 61.0
    assert _parse_odds("-") is None
    assert _parse_odds("0,90") is None  # <= 1.0 no es una cuota apostable
