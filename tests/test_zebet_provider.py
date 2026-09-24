from providers.zebet import ZebetProvider

# Forma real de los datos extraídos del DOM de Zebet (ver _EXTRACT_EVENTS_JS),
# capturada en vivo el 2026-09-24 en la página de competición de LaLiga.
RAW_EVENTS = [
    {"teams": ["Málaga", "Espanyol"], "odds": ["2,50", "3,00", "2,57"], "href": "/es/event/cikj3-malaga_espanyol"},
    {"teams": ["Real Madrid", "Sevilla"], "odds": ["1,23", "5,30", "7,25"], "href": None},
]


def test_parses_1x2_and_href_from_raw_dom_events():
    provider = ZebetProvider()
    events = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(events) == 2
    event_name, market, href = next(e for e in events if "Espanyol" in e[0])
    assert event_name == "Málaga vs. Espanyol"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.50), ("X", 3.00), ("2", 2.57)]
    assert all(o.bookmaker == "zebet" for o in market.outcomes)
    assert href == "/es/event/cikj3-malaga_espanyol"

    _, _, no_href = next(e for e in events if "Sevilla" in e[0])
    assert no_href is None


def test_decimal_comma_is_converted_to_a_point():
    provider = ZebetProvider()
    ((_, market, _),) = provider._parse_events([{"teams": ["A", "B"], "odds": ["1,23", "5,30", "7,25"]}], "futbol")
    assert [o.odds for o in market.outcomes] == [1.23, 5.30, 7.25]


def test_skips_malformed_or_incomplete_events_but_keeps_the_event_name():
    provider = ZebetProvider()
    cases = [
        {"teams": ["A", "B"], "odds": ["1,50", "3,00"]},  # falta una cuota
        {"teams": ["A", "B"], "odds": ["1,50", None, "2,50"]},  # empate suspendido
        {"teams": ["A", "B"], "odds": ["1,00", "3,00", "2,50"]},  # cuota 1.00: no apostable
    ]
    events = provider._parse_events(cases, "futbol")
    assert len(events) == 3
    assert all(market is None for _, market, _ in events)

    # sin ambos equipos: se descarta el partido entero, ni siquiera el nombre
    assert provider._parse_events([{"teams": [], "odds": ["1,50", "3,00", "2,50"]}], "futbol") == []
    assert provider._parse_events([{"teams": ["Un solo equipo"], "odds": ["1,50", "3,00", "2,50"]}], "futbol") == []


def test_competition_urls_default_to_laliga():
    provider = ZebetProvider()
    assert provider.competition_urls["futbol"] == "https://www.zebet.es/es/competition/306-laliga"


# --- mercados de la ficha del partido (Doble oportunidad, Ambos marcan, Par/Impar,
# Más/Menos, Hándicap) -----------------------------------------------------------

def block(data_t, question, odds, labels):
    return {"dataT": data_t, "question": question, "odds": odds, "labels": labels}


# Forma real de los bloques de _EXTRACT_MATCH_EXTRAS_JS, capturada en vivo el
# 2026-09-24 en dos partidos distintos de LaLiga (Unicaja Málaga vs. Espanyol).
REAL_BLOCKS = [
    block("Doble oportunidad", "¿Doble oportunidad? ? .", ["1,36", "1,29", "1,38"], ["1X", "12", "X2"]),
    block(
        "¿Ambos equipos marcarán al menos un gol?",
        "¿Ambos equipos marcarán al menos un gol?",
        ["1,75", "1,87"],
        ["Si", "No"],
    ),
    # Par-Impar del partido completo: sin nombre de equipo en la pregunta.
    block("Par - Impar", "¿El número de goles marcados será par o impar?", ["1,88", "1,75"], ["Impar", "Par"]),
    # Par-Impar por equipo, MISMO data-t: debe descartarse (pregunta distinta).
    block("Par - Impar", "¿Número de goles del Unicaja Málaga, par o impar?", ["1,93", "1,68"], ["Impar", "Par"]),
    # Más/Menos del partido completo: varias líneas bajo la misma pregunta, con un
    # último bloque vacío (visto en vivo, un input de línea personalizada sin cuota).
    block(
        "Más de / Menos de",
        "¿Más o menos de goles?",
        ["1,05", "5,90", "1,30", "2,87", "1,95", "1,65", "3,20", "1,23", "5,30", "1,06"],
        [
            "Más de 0.5", "Menos de 0.5", "Más de 1.5", "Menos de 1.5", "Más de 2.5", "Menos de 2.5",
            "Más de 3.5", "Menos de 3.5", "Más de 4.5", "Menos de 4.5",
        ],
    ),
    block("Más de / Menos de", "¿Más o menos de goles en el 1o tiempo?", ["1,40", "2,52"], ["Más de 0.5", "Menos de 0.5"]),
    block(
        "Más de / Menos de (2a mitad)",
        "¿Más o menos de goles en la 2ª mitad?",
        ["1,23", "3,30", "2,17", "1,55"],
        ["Más de 0.5", "Menos de 0.5", "Más de 1.5", "Menos de 1.5"],
    ),
    # Hándicap decimal (cruza) - partido completo y 1ª mitad.
    block("Handicap 1-2", "Hándicap (-0.5) - ¿Quién ganará el partido?", ["2,37", "1,43"], ["Unicaja Málaga (-0.5)", "Espanyol (+0.5)"]),
    block("Handicap 1-2", "Hándicap (+1.5) - ¿Quién ganará el partido?", ["1,11", "4,40"], ["Unicaja Málaga (+1.5)", "Espanyol (-1.5)"]),
    block(
        "Hándicap del periodo",
        "Hándicap (-0.5) - ¿Quién ganará la 1ª mitad?",
        ["2,77", "1,28"],
        ["Unicaja Málaga (-0.5)", "Espanyol (+0.5)"],
    ),
    # 2ª mitad: la etiqueta NO repite la línea (visto en vivo), la línea solo está
    # en la pregunta - por eso _parse_ah_block nunca debe leerla de la etiqueta.
    block("Margen al descanso", "Hándicap (-0.5) - ¿Quién ganará la 2ª mitad?", ["2,57", "1,33"], ["Unicaja Málaga", "Espanyol"]),
    # Hándicap de marcador (NO cruza, 3 resultados): debe descartarse.
    block(
        "Hándicap",
        "Hándicap (0:1) - ¿Quién ganará el partido?",
        ["5,30", "4,20", "1,45"],
        ["Unicaja Málaga (-1)", "Empate (-1)", "Espanyol (+1)"],
    ),
    # Ruido: un mercado no soportado no debe romper nada ni colarse.
    block("Puntuación exacta", "¿Resultado múltiple?", ["9,0", "7,0"], ["0-0", "1-0"]),
]


def test_double_chance_btts_and_full_match_odd_even_are_parsed():
    markets = {m.market_type: m for m in ZebetProvider()._parse_match_extras(REAL_BLOCKS, "A vs. B", "futbol")}
    assert [(o.name, o.odds) for o in markets["DC"].outcomes] == [("1X", 1.36), ("12", 1.29), ("X2", 1.38)]
    assert [(o.name, o.odds) for o in markets["BTTS"].outcomes] == [("Yes", 1.75), ("No", 1.87)]
    assert [(o.name, o.odds) for o in markets["OE"].outcomes] == [("Odd", 1.88), ("Even", 1.75)]
    assert all(m.event == "A vs. B" and m.sport == "futbol" for m in markets.values())


def test_per_team_odd_even_sharing_the_same_data_t_is_not_confused_with_the_full_match_one():
    markets = ZebetProvider()._parse_match_extras(REAL_BLOCKS, "A vs. B", "futbol")
    oe_markets = [m for m in markets if m.market_type == "OE"]
    assert len(oe_markets) == 1  # el bloque "por equipo" (misma data-t) no se emite
    assert [(o.name, o.odds) for o in oe_markets[0].outcomes] == [("Odd", 1.88), ("Even", 1.75)]


def test_over_under_lines_are_paired_and_split_by_period():
    markets = {m.market_type: m for m in ZebetProvider()._parse_match_extras(REAL_BLOCKS, "A vs. B", "futbol")}
    assert [(o.name, o.odds) for o in markets["OU_0.5"].outcomes] == [("Over", 1.05), ("Under", 5.90)]
    assert [(o.name, o.odds) for o in markets["OU_2.5"].outcomes] == [("Over", 1.95), ("Under", 1.65)]
    assert [(o.name, o.odds) for o in markets["OU_HT_0.5"].outcomes] == [("Over", 1.40), ("Under", 2.52)]
    assert [(o.name, o.odds) for o in markets["OU_2H_1.5"].outcomes] == [("Over", 2.17), ("Under", 1.55)]


def test_decimal_handicap_crosses_but_scoreline_handicap_is_dropped():
    markets = {m.market_type: m for m in ZebetProvider()._parse_match_extras(REAL_BLOCKS, "A vs. B", "futbol")}
    assert [(o.name, o.odds) for o in markets["AH_-0.5"].outcomes] == [("1", 2.37), ("2", 1.43)]
    assert [(o.name, o.odds) for o in markets["AH_+1.5"].outcomes] == [("1", 1.11), ("2", 4.40)]
    # 2ª mitad: la línea se lee de la pregunta aunque la etiqueta no la repita.
    assert [(o.name, o.odds) for o in markets["AH_HT_-0.5"].outcomes] == [("1", 2.77), ("2", 1.28)]
    assert [(o.name, o.odds) for o in markets["AH_2H_-0.5"].outcomes] == [("1", 2.57), ("2", 1.33)]
    assert not any(t.startswith("AH") and "0:1" in t for t in markets)
    ah_types = [t for t in markets if t.startswith("AH")]
    assert len(ah_types) == 4  # las 4 líneas decimales de REAL_BLOCKS, ninguna de marcador


def test_unsupported_markets_and_broken_blocks_are_silently_skipped():
    types = {m.market_type for m in ZebetProvider()._parse_match_extras(REAL_BLOCKS, "A vs. B", "futbol")}
    assert not any(t.startswith("CS") or "multiple" in t.lower() for t in types)


def test_duplicate_market_types_are_only_emitted_once():
    duplicated = REAL_BLOCKS + [REAL_BLOCKS[0]]  # Doble oportunidad repetida
    markets = ZebetProvider()._parse_match_extras(duplicated, "A vs. B", "futbol")
    assert len([m for m in markets if m.market_type == "DC"]) == 1


def test_labelled_market_rejects_unknown_or_incomplete_labels():
    provider = ZebetProvider()
    from providers.zebet import _BTTS_LABELS

    assert provider._parse_labelled_market(["1,75"], ["Si"], _BTTS_LABELS, "BTTS", "A vs. B", "futbol") is None
    assert provider._parse_labelled_market(["1,75", "1,87"], ["Sí", "No"], _BTTS_LABELS, "BTTS", "A vs. B", "futbol") is None
    assert (
        provider._parse_labelled_market(["1,75", "1,87", "2,0"], ["Si", "No", "Si"], _BTTS_LABELS, "BTTS", "A vs. B", "futbol")
        is None
    )
