from datetime import datetime, timedelta, timezone

from providers.altenar import (
    FOOTBALL_MARKET_SPECS,
    AltenarProvider,
    _display_price,
    _fmt_line,
    parse_event_markets,
)


HOME, AWAY = 100, 200


def _odd(odd_id, name, price, status=0, team=None):
    return {"id": odd_id, "name": name, "price": price, "oddStatus": status, "typeId": 0, "competitorId": team}


def _market(market_id, type_id, odd_ids, is_bb=False):
    return {"id": market_id, "typeId": type_id, "isBB": is_bb, "desktopOddIds": [odd_ids]}


DETAILS = {
    "odds": [
        _odd(1, "1", 2.7143, team=HOME),
        _odd(2, "Empate", 3.3334),
        _odd(3, "2", 2.625, team=AWAY),
        # Total de goles: dos líneas completas + una línea de cuarto + una sin pareja
        _odd(10, "Más de 2.5", 1.95),
        _odd(11, "Menos de 2.5", 1.85),
        _odd(12, "Más de 2.25", 1.7),
        _odd(13, "Menos de 2.25", 2.1),
        _odd(14, "Más de 3.5", 3.25),
        # Córners
        _odd(20, "Más de 9.5", 2.05),
        _odd(21, "Menos de 9.5", 1.8),
        # Hándicap: "1 (+1.75)" empareja con "2 (-1.75)"
        _odd(30, "1 (+1.75)", 1.2, team=HOME),
        _odd(31, "2 (-1.75)", 4.2, team=AWAY),
        _odd(32, "1 (-0.5)", 2.0, team=HOME),
        _odd(33, "2 (+0.5)", 1.8, team=AWAY),
        # Ambos marcan, con una cuota suspendida
        _odd(40, "Sí", 1.71),
        _odd(41, "No", 2.1, status=1),
        # Impar/Par
        _odd(50, "Impar", 2.0),
        _odd(51, "Par", 1.8),
        # Resultado desconocido en un 1x2 de tarjetas
        _odd(60, "1", 3.1, team=HOME),
        _odd(61, "Otro", 3.6),
        _odd(62, "2", 1.9, team=AWAY),
    ],
    "competitors": [{"id": HOME, "name": "Local"}, {"id": AWAY, "name": "Visitante"}],
    "markets": [
        _market(100, 1, [1, 2, 3]),
        # misma id de mercado duplicada (vista "Crear apuesta", con menos líneas)
        _market(100, 1, [1, 2, 3], is_bb=True),
        _market(101, 18, [10, 11, 12, 13, 14]),
        _market(101, 18, [10, 11], is_bb=True),
        _market(102, 166, [20, 21]),
        _market(103, 16, [30, 31, 32, 33]),
        _market(104, 29, [40, 41]),
        _market(105, 26, [50, 51]),
        _market(106, 136, [60, 61, 62]),
        # tipo de mercado no soportado (marcador exacto)
        _market(107, 45, [1, 2]),
    ],
}


def _by_type(markets):
    return {m.market_type: m for m in markets}


def test_parses_supported_markets_and_ignores_unsupported():
    markets = parse_event_markets(DETAILS, "Valencia CF vs. Real Sociedad", "futbol", "betway")
    types = set(_by_type(markets))

    assert "1X2" in types
    assert "OU_2.5" in types
    assert "CORNERS_OU_9.5" in types
    assert all(m.event == "Valencia CF vs. Real Sociedad" and m.sport == "futbol" for m in markets)
    assert all(o.bookmaker == "betway" for m in markets for o in m.outcomes)


def test_duplicate_bet_builder_variant_is_not_emitted_twice():
    markets = parse_event_markets(DETAILS, "A vs. B", "futbol", "betway")
    assert sum(1 for m in markets if m.market_type == "1X2") == 1


def test_one_x_two_names_and_rounded_prices():
    market = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))["1X2"]
    assert [(o.name, o.odds) for o in market.outcomes if o.name in ("1", "X", "2")] == [
        ("1", 2.71),
        ("X", 3.33),
        ("2", 2.63),
    ]


def test_over_under_lines_are_paired_and_quarter_line_becomes_split_line():
    types = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))

    assert {o.name for o in types["OU_2.5"].outcomes} == {"Over", "Under"}
    assert "OU_2/2.5" in types
    # "Más de 3.5" no tiene su "Menos de 3.5": no se emite un mercado incompleto
    assert "OU_3.5" not in types


def test_asian_handicap_pairs_both_sides_using_the_home_line():
    types = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))

    assert [(o.name, o.odds) for o in types["AH_-0.5"].outcomes] == [("1", 2.0), ("2", 1.8)]
    # línea de cuarto +1.75: se expresa como dos líneas sin signo, la más cercana a cero primero
    assert "AH_1.5/2" in types


def test_market_with_a_suspended_outcome_is_dropped():
    types = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))
    assert "BTTS" not in types


def test_odd_even_uses_same_names_as_other_providers():
    market = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))["OE"]
    assert [(o.name, o.odds) for o in market.outcomes] == [("Odd", 2.0), ("Even", 1.8)]


def test_market_with_unknown_outcome_name_is_dropped_entirely():
    types = _by_type(parse_event_markets(DETAILS, "A vs. B", "futbol", "betway"))
    assert "CARDS_1X2" not in types


def test_display_price_rounds_half_up_like_javascript_tofixed():
    assert _display_price(2.625) == 2.63
    assert _display_price(2.7143) == 2.71
    assert _display_price(1.056) == 1.06


def test_line_formatting():
    assert _fmt_line(2.5) == "2.5"
    assert _fmt_line(2.0) == "2"
    assert _fmt_line(2.25) == "2/2.5"
    assert _fmt_line(-2.25) == "-2/-2.5"
    assert _fmt_line(-0.25, signed=True) == "0/-0.5"
    assert _fmt_line(0.5, signed=True) == "+0.5"
    assert _fmt_line(-0.5, signed=True) == "-0.5"


def test_market_specs_have_unique_market_types_per_kind():
    prefixes = [prefix for prefix, _ in FOOTBALL_MARKET_SPECS.values()]
    assert len(prefixes) == len(set(prefixes))


class _FakeProvider(AltenarProvider):
    """AltenarProvider con la red sustituida por datos fijos."""

    def __init__(self, listings, details):
        super().__init__(integrations={"casa_a": "casa_a", "casa_b": "casa_b", "casa_c": "casa_c"}, horizon_hours=48)
        self._listings = listings
        self._details = details

    def _get_json(self, client, endpoint, integration, **params):
        if endpoint == "GetEvents":
            return {"events": self._listings[integration]}
        return self._details


def _event(event_id, name, hours_ahead=5, status=0):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": event_id, "name": name, "status": status, "startDate": start}


def test_only_events_listed_by_at_least_two_houses_are_fetched_with_shared_name():
    provider = _FakeProvider(
        listings={
            "casa_a": [_event(1, "Valencia CF vs. Real Sociedad"), _event(2, "Solo A vs. Solo B")],
            "casa_b": [_event(1, "Valencia vs. Real Sociedad")],
            "casa_c": [],
        },
        details=DETAILS,
    )

    markets = provider._fetch_football(client=None)

    assert {m.event for m in markets} == {"Valencia CF vs. Real Sociedad"}
    assert {o.bookmaker for m in markets for o in m.outcomes} == {"casa_a", "casa_b"}


def test_live_or_out_of_horizon_events_are_ignored():
    provider = _FakeProvider(
        listings={
            "casa_a": [_event(1, "A vs. B", status=1), _event(2, "C vs. D", hours_ahead=200)],
            "casa_b": [_event(1, "A vs. B", status=1), _event(2, "C vs. D", hours_ahead=200)],
            "casa_c": [],
        },
        details=DETAILS,
    )

    assert provider._fetch_football(client=None) == []


def test_returns_nothing_when_no_football_sport_requested():
    assert AltenarProvider().fetch_markets(["baloncesto_nba"]) == []


TEAM_NAME_STYLE = {
    # Estilo Jokerbet/Pastón: el resultado lleva el nombre del equipo, no "1"/"2"
    "odds": [
        _odd(1, "Valencia", 2.625, team=HOME),
        _odd(2, "X", 3.25),
        _odd(3, "Real Sociedad", 2.6, team=AWAY),
        _odd(10, "Valencia (-0.5)", 2.55, team=HOME),
        _odd(11, "Real Sociedad (+0.5)", 1.48, team=AWAY),
        _odd(12, "Valencia (+0.5)", 1.48, team=HOME),
        _odd(13, "Real Sociedad (-0.5)", 2.55, team=AWAY),
        _odd(20, "Ambos Marcan: Si", 1.69),
        _odd(21, "Ambos Marcan: No", 2.05),
        _odd(30, "Valencia", 1.83, team=HOME),
        _odd(31, "Real Sociedad", 1.83, team=AWAY),
    ],
    "markets": [
        _market(1, 1, [1, 2, 3]),
        _market(2, 16, [10, 11, 12, 13]),
        _market(3, 29, [20, 21]),
        _market(4, 11, [30, 31]),
    ],
    "competitors": [{"id": HOME, "name": "Valencia"}, {"id": AWAY, "name": "Real Sociedad"}],
}


def test_team_name_outcomes_are_identified_by_competitor_id_not_text():
    types = _by_type(parse_event_markets(TEAM_NAME_STYLE, "A vs. B", "futbol", "paston"))

    assert [(o.name, o.odds) for o in types["1X2"].outcomes] == [("1", 2.63), ("X", 3.25), ("2", 2.6)]
    assert [(o.name, o.odds) for o in types["DNB"].outcomes] == [("1", 1.83), ("2", 1.83)]


def test_team_name_handicaps_pair_home_and_away_lines_correctly():
    types = _by_type(parse_event_markets(TEAM_NAME_STYLE, "A vs. B", "futbol", "paston"))

    # local -0.5 va con visitante +0.5; local +0.5 con visitante -0.5
    assert [(o.name, o.odds) for o in types["AH_-0.5"].outcomes] == [("1", 2.55), ("2", 1.48)]
    assert [(o.name, o.odds) for o in types["AH_+0.5"].outcomes] == [("1", 1.48), ("2", 2.55)]


def test_yes_no_accepts_paston_prefixed_labels():
    types = _by_type(parse_event_markets(TEAM_NAME_STYLE, "A vs. B", "futbol", "paston"))
    assert [(o.name, o.odds) for o in types["BTTS"].outcomes] == [("Yes", 1.69), ("No", 2.05)]


def test_explicit_competitor_ids_override_details_order():
    swapped = parse_event_markets(TEAM_NAME_STYLE, "A vs. B", "futbol", "paston", competitor_ids=(AWAY, HOME))
    types = _by_type(swapped)
    assert [(o.name, o.odds) for o in types["DNB"].outcomes] == [("2", 1.83), ("1", 1.83)]


def test_get_json_retries_when_altenar_rate_limits_requests(monkeypatch):
    # Con 5 casas y varios hilos Altenar responde 429 de vez en cuando; antes se
    # perdía entera la casa/partido de esa petición (p.ej. DAZN Bet).
    import time

    from providers.altenar import AltenarProvider

    monkeypatch.setattr(time, "sleep", lambda s: None)

    class Response:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class Client:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = 0

        def get(self, url, params=None):
            self.calls += 1
            return self.responses.pop(0)

    provider = AltenarProvider()
    client = Client([Response(429), Response(429), Response(200, {"events": []})])
    assert provider._get_json(client, "GetEvents", "daznbet") == {"events": []}
    assert client.calls == 3

    always_limited = Client([Response(429)] * 5)
    try:
        provider._get_json(always_limited, "GetEvents", "daznbet")
    except RuntimeError as exc:
        assert "límite de peticiones" in str(exc)
    else:
        raise AssertionError("debió fallar tras agotar los reintentos")


def test_esports_and_womens_football_are_excluded_by_champ_and_category_names():
    start = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def ev(event_id, name, champ_id, cat_id):
        return {"id": event_id, "name": name, "status": 0, "startDate": start, "champId": champ_id, "catId": cat_id}

    data = {
        "champs": [
            {"id": 1, "name": "LaLiga"},
            {"id": 2, "name": "ESportsBattle. Portugal Primera (2x4 mins)"},
            {"id": 3, "name": "Liga MX, Femenino"},
            {"id": 4, "name": "FIFA ASEAN Cup"},
        ],
        "categories": [{"id": 10, "name": "España"}, {"id": 11, "name": "E-battles"}, {"id": 12, "name": "México"}, {"id": 13, "name": "Asia"}],
        "events": [
            ev(1, "Valencia vs. Sevilla", 1, 10),
            ev(2, "Porto (kozak) vs. Benfica (drksd3)", 2, 11),
            ev(3, "Chivas vs. Tigres", 3, 12),
            ev(4, "Vietnam vs. Tailandia", 4, 13),  # torneo real: "FIFA" por sí solo no es e-soccer
        ],
    }

    def listed(**kwargs):
        provider = AltenarProvider(integrations={"c": "c"}, horizon_hours=48, **kwargs)
        provider._get_json = lambda client, endpoint, integration, **params: data
        return set(provider._list_events(None, "c"))

    assert listed() == {1, 4}
    assert listed(exclude_women=False) == {1, 3, 4}
    assert listed(exclude_esports=False) == {1, 2, 4}


def _dc_odd(odd_id, name, price, type_id, status=0):
    odd = _odd(odd_id, name, price, status=status)
    odd["typeId"] = type_id
    return odd


def _dc_details(*odds, market_type=10):
    return {
        "odds": list(odds),
        "competitors": [{"id": HOME, "name": "Local"}, {"id": AWAY, "name": "Visitante"}],
        "markets": [_market(500, market_type, [o["id"] for o in odds])],
    }


def test_double_chance_is_identified_by_odd_type_not_by_text_and_covers_halves():
    # Betway: "1 o empate"; Jokerbet/Pastón usan el nombre del equipo: el typeId es el mismo
    for names in (("1 o empate", "1 o  2", "Empate o 2"), ("Valencia o empate", "Valencia o Real Sociedad", "Empate o Real Sociedad")):
        details = _dc_details(_dc_odd(1, names[0], 1.1765, 9), _dc_odd(2, names[1], 1.2308, 10), _dc_odd(3, names[2], 2.0, 11))
        (market,) = parse_event_markets(details, "Local vs. Visitante", "futbol", "betway")
        assert market.market_type == "DC"
        assert [(o.name, o.odds) for o in market.outcomes] == [("1X", 1.18), ("12", 1.23), ("X2", 2.0)]
    for type_id, expected in ((63, "DC_HT"), (85, "DC_2H")):
        details = _dc_details(_dc_odd(1, "a", 1.5, 9), _dc_odd(2, "b", 1.4, 10), _dc_odd(3, "c", 2.5, 11), market_type=type_id)
        assert [m.market_type for m in parse_event_markets(details, "L vs. V", "futbol", "x")] == [expected]


def test_double_chance_with_a_suspended_or_unknown_selection_is_dropped():
    suspended = _dc_details(_dc_odd(1, "a", 1.5, 9), _dc_odd(2, "b", 1.4, 10), _dc_odd(3, "c", 2.5, 11, status=1))
    unknown = _dc_details(_dc_odd(1, "a", 1.5, 9), _dc_odd(2, "b", 1.4, 10), _dc_odd(3, "c", 2.5, 99))
    assert parse_event_markets(suspended, "L vs. V", "futbol", "x") == []
    assert parse_event_markets(unknown, "L vs. V", "futbol", "x") == []
