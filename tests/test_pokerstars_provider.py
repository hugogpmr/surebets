from providers.pokerstars import (
    PokerStarsProvider,
    _extract_line,
    _parse_btts_table,
    _parse_odds,
    _parse_ou_table,
    _parse_three_way_table,
    parse_extra_markets,
)

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


# --- Mercados nuevos de la ficha de partido (2026-09-25) ---
# Formas reales capturadas en vivo el 2026-09-25 (Italia-Bélgica, UEFA Nations
# League) inspeccionando el DOM directamente (ver README para el hallazgo:
# cada <details> tiene su contenido en el DOM aunque esté colapsado).
HOME, AWAY = "Italia", "Bélgica"
EVENT_NAME = f"{HOME} vs. {AWAY}"


def test_extract_line_from_varied_row_text():
    assert _extract_line("6,5 córneres en total") == "6.5"
    assert _extract_line("Córneres - Más/menos de 8,5") == "8.5"
    assert _extract_line("Más/Menos de 0,5 Goles") == "0.5"
    assert _extract_line("Goles en la 1.a mitad - 2,5") == "2.5"
    assert _extract_line("sin números") is None


def test_parse_ou_table_goals():
    headers = ["", "Más de", "Menos de"]
    rows = [
        ["Más/Menos de 0,5 Goles", "1,02", "11,00"],
        ["Más/Menos de 2,5 Goles", "1,57", "2,25"],
    ]
    markets = _parse_ou_table(headers, rows, "OU_{line}", EVENT_NAME)
    types = {m.market_type for m in markets}
    assert types == {"OU_0.5", "OU_2.5"}
    ou25 = next(m for m in markets if m.market_type == "OU_2.5")
    assert [(o.name, o.odds) for o in ou25.outcomes] == [("Over", 1.57), ("Under", 2.25)]


def test_parse_ou_table_rejects_unknown_headers():
    # Cabeceras que no son "Más de"/"Menos de" ni "Sí"/"No" (p.ej. una tabla
    # de resultado exacto colada por error): no se adivina, se descarta.
    headers = ["", "Local", "Visitante"]
    rows = [["1-0", "10,00", "13,00"]]
    assert _parse_ou_table(headers, rows, "OU_{line}", EVENT_NAME) == []


def test_parse_ou_table_skips_row_without_line():
    headers = ["", "Más de", "Menos de"]
    rows = [["sin línea reconocible", "1,50", "2,50"]]
    assert _parse_ou_table(headers, rows, "OU_{line}", EVENT_NAME) == []


def test_parse_btts_table_picks_only_known_rows():
    # La tabla real mezcla BTTS simple con otras variantes (sin empate, 2+
    # goles cada uno...) que no tienen forma Sí/No de 2 resultados fijos aquí,
    # o no cruzan con ninguna otra fuente: solo se quedan las 2 filas conocidas.
    headers = ["", "Sí", "No"]
    rows = [
        ["¿Ambos equipos anotan?", "1,47", "2,63"],
        ["Ambos equipos anotan - Sin empate", "2,25", "1,57"],
        ["Ambos Equipos Marcan en la 1ª Parte", "3,25", "1,29"],
    ]
    markets = _parse_btts_table(headers, rows, EVENT_NAME)
    by_type = {m.market_type: [(o.name, o.odds) for o in m.outcomes] for m in markets}
    assert by_type == {
        "BTTS": [("Yes", 1.47), ("No", 2.63)],
        "BTTS_HT": [("Yes", 3.25), ("No", 1.29)],
    }


def test_parse_three_way_table_half_time_result():
    headers = [HOME, "Empate", AWAY]
    rows = [["2,63", "2,30", "3,40"]]
    markets = _parse_three_way_table(headers, rows, "1X2_HT", HOME, AWAY, EVENT_NAME)
    assert len(markets) == 1
    assert [(o.name, o.odds) for o in markets[0].outcomes] == [("1", 2.63), ("X", 2.30), ("2", 3.40)]


def test_parse_three_way_table_rejects_unmatched_headers():
    # Cabeceras que no encajan con home/away/"Empate" (p.ej. un cambio de
    # texto en la web, o una tabla de otro tipo): no se fabrica un mercado.
    headers = [HOME, "Otro texto", AWAY]
    rows = [["2,63", "2,30", "3,40"]]
    assert _parse_three_way_table(headers, rows, "1X2_HT", HOME, AWAY, EVENT_NAME) == []


def test_parse_extra_markets_end_to_end():
    accordions = [
        {"title": "Descanso", "headers": [HOME, "Empate", AWAY], "rows": [["2,63", "2,30", "3,40"]]},
        {
            "title": "Más/menos de goles",
            "headers": ["", "Más de", "Menos de"],
            "rows": [["Más/Menos de 2,5 Goles", "1,57", "2,25"]],
        },
        {
            "title": "Mercados de Ambos equipos anotan",
            "headers": ["", "Sí", "No"],
            "rows": [["¿Ambos equipos anotan?", "1,47", "2,63"]],
        },
        {
            "title": "Total de córneres",
            "headers": ["", "Más de", "Menos de"],
            "rows": [["6,5 córneres en total", "1,14", "4,80"]],
        },
        {"title": "Equipo con más corners totales", "headers": [HOME, "Empate", AWAY], "rows": [["1,83", "7,00", "2,30"]]},
        # Rechazado: hándicap de córners a 3 vías, mismo patrón ya visto en
        # Zebet/Versus/888sport/William Hill - no debe fabricar AH ni colarse.
        {"title": "Hándicap de Córners", "headers": [HOME, "Empate", AWAY], "rows": [["2,30", "7,00", "1,83"]]},
        # Mercado irrelevante (goleadores): debe ignorarse sin fallar.
        {"title": "¿El jugador anota un hat trick?", "headers": ["Jugador", ""], "rows": [["Lukaku", "51,00"]]},
    ]
    markets = parse_extra_markets(accordions, HOME, AWAY)
    types = {m.market_type for m in markets}
    assert types == {"1X2_HT", "OU_2.5", "BTTS", "CORNERS_OU_6.5", "CORNERS_1X2"}
    assert all(m.event == EVENT_NAME for m in markets)


def test_parse_extra_markets_deduplicates_by_market_type():
    # La misma pestaña puede en teoría repetir un mercado (visto en otras
    # casas de este repo): solo debe quedarse con el primero.
    descanso = {"title": "Descanso", "headers": [HOME, "Empate", AWAY], "rows": [["2,63", "2,30", "3,40"]]}
    markets = parse_extra_markets([descanso, descanso], HOME, AWAY)
    assert [m.market_type for m in markets] == ["1X2_HT"]
