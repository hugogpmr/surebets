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


# Forma real de los datos extraídos de la ficha del partido (ver
# _EXTRACT_MATCH_EXTRAS_JS), capturada en vivo el 2026-09-24.
RAW_EXTRAS = {
    "dc": {"odds": ["1,36", "1,29", "1,38"], "labels": ["1X", "12", "X2"]},
    "btts": {"odds": ["1,75", "1,87"], "labels": ["Si", "No"]},
    "oe": {"odds": ["1,88", "1,77"], "labels": ["Impar", "Par"]},
}


def test_parses_double_chance_btts_and_odd_even_from_the_match_page():
    provider = ZebetProvider()
    markets = {m.market_type: m for m in provider._parse_match_extras(RAW_EXTRAS, "A vs. B", "futbol")}

    assert [(o.name, o.odds) for o in markets["DC"].outcomes] == [("1X", 1.36), ("12", 1.29), ("X2", 1.38)]
    assert [(o.name, o.odds) for o in markets["BTTS"].outcomes] == [("Yes", 1.75), ("No", 1.87)]
    assert [(o.name, o.odds) for o in markets["OE"].outcomes] == [("Odd", 1.88), ("Even", 1.77)]
    assert all(m.event == "A vs. B" and m.sport == "futbol" for m in markets.values())
    assert all(o.bookmaker == "zebet" for m in markets.values() for o in m.outcomes)


def test_missing_market_block_is_just_skipped():
    raw = {"dc": None, "btts": RAW_EXTRAS["btts"], "oe": None}
    markets = provider_markets(raw)
    assert {m.market_type for m in markets} == {"BTTS"}


def test_unknown_label_or_wrong_outcome_count_is_rejected():
    cases = [
        {"odds": ["1,75"], "labels": ["Si"]},  # falta "No"
        {"odds": ["1,75", "1,87"], "labels": ["Sí", "No"]},  # "Sí" con tilde: no es la etiqueta real de la web
        {"odds": ["1,75", "1,87", "2,00"], "labels": ["Si", "No", "Si"]},  # repetida
    ]
    for btts in cases:
        raw = {"dc": None, "btts": btts, "oe": None}
        assert provider_markets(raw) == []


def provider_markets(raw):
    return ZebetProvider()._parse_match_extras(raw, "A vs. B", "futbol")
