from datetime import datetime, timezone

from providers.williamhill import (
    _all_markets,
    _decimal_odds,
    _double_chance,
    _over_under_lines,
    _parse_event,
    _team_two_way,
    _three_way,
    _two_way,
    parse_extra_markets,
)

# Forma real de un evento pre-partido de la API (capturado en vivo el
# 2026-09-23, Azerbaiyán-Tayikistán): mercado "Ganador del partido" con cuota
# fraccionaria (currentPriceNum/currentPriceDen). El orden de selecciones no es
# fiable por índice (se identifica "Empate" por nombre, ver providers/williamhill.py).
def _selection(name: str, num: int, den: int, order: int, status: str = "A") -> dict:
    return {
        "name": name,
        "currentPriceNum": num,
        "currentPriceDen": den,
        "order": order,
        "status": status,
        "active": True,
        "displayed": True,
    }


REAL_1X2_MARKET = {
    "name": "Ganador del partido",
    "marketGroupNameToken": "|Ganador del partido|",
    "status": "A",
    "selections": [
        _selection("Azerbaiyán", 78, 100, 10),
        _selection("Empate", 12, 5, 20),
        _selection("Tayikistán", 16, 5, 30),
    ],
}

PROMO_2UP_MARKET = {
    "name": "Ganador del partido",
    "marketGroupNameToken": "|90 Minutes - 2 Up - Spain|",
    "status": "A",
    "selections": REAL_1X2_MARKET["selections"],
}


def _event(markets: list[dict], **overrides) -> dict:
    base = {
        "id": "OB_EV1",
        "startDateTime": "2026-09-23T16:00:00.000+0000",
        "isInPlay": False,
        "settled": False,
        "status": "A",
        "markets": markets,
    }
    base.update(overrides)
    return base


def test_parses_real_1x2_market():
    market = _parse_event(_event([REAL_1X2_MARKET]), "Amistosos internacionales")
    assert market is not None
    assert market.event == "Azerbaiyán vs. Tayikistán"
    assert market.market_type == "1X2"
    assert market.start_time == datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
    assert [(o.name, round(o.odds, 2)) for o in market.outcomes] == [("1", 1.78), ("X", 3.4), ("2", 4.2)]
    assert all(o.bookmaker == "williamhill" for o in market.outcomes)


def test_skips_in_play_event():
    assert _parse_event(_event([REAL_1X2_MARKET], isInPlay=True), "Liga") is None


def test_skips_settled_event():
    assert _parse_event(_event([REAL_1X2_MARKET], settled=True), "Liga") is None


def test_market_named_ganador_del_partido_but_its_the_2up_promo_is_matched_by_name_only():
    # providers/williamhill.py filtra por marketType en la petición, no por el
    # texto del mercado (la promo "2 Up" también se llama "Ganador del
    # partido" puertas afuera). Aquí solo se comprueba que _parse_event, dado
    # un evento cuyo único mercado ES la promo, igual lo parsea (la exclusión
    # real pasa por pedir el grupo correcto en la API, ver docstring) —
    # documenta el riesgo si algún día se cambia el `marketType` de la query.
    market = _parse_event(_event([PROMO_2UP_MARKET]), "Liga")
    assert market is not None  # aviso: solo se distingue por el marketType pedido a la API


def test_skips_when_no_matching_market():
    event = _event([{"name": "Doble oportunidad", "status": "A", "selections": []}])
    assert _parse_event(event, "Liga") is None


def test_skips_when_selection_suspended():
    market = {
        "name": "Ganador del partido",
        "status": "A",
        "selections": [
            _selection("Azerbaiyán", 78, 100, 10, status="S"),
            _selection("Empate", 12, 5, 20),
            _selection("Tayikistán", 16, 5, 30),
        ],
    }
    assert _parse_event(_event([market]), "Liga") is None


def test_excludes_womens_football_by_competition_name():
    assert _parse_event(_event([REAL_1X2_MARKET]), "English FA Women's League Cup") is None


def test_decimal_odds_from_fraction():
    assert _decimal_odds({"currentPriceNum": 78, "currentPriceDen": 100, "status": "A", "active": True, "displayed": True}) == 1.78
    assert _decimal_odds({"currentPriceNum": 1, "currentPriceDen": 1, "status": "A", "active": True, "displayed": True}) == 2.0
    assert _decimal_odds({"currentPriceNum": 1, "currentPriceDen": 1, "status": "S", "active": True, "displayed": True}) is None
    assert _decimal_odds({"currentPriceNum": 1, "currentPriceDen": 0, "status": "A", "active": True, "displayed": True}) is None


# --- Mercados nuevos de la ficha de partido (2026-09-25) ---
# Formas reales capturadas en vivo el 2026-09-25 (Atletico Nacional-Millonarios,
# Colombia - Primera División), ver README para el detalle del hallazgo.
HOME, AWAY = "Atletico Nacional", "Millonarios"
EVENT_NAME = f"{HOME} vs. {AWAY}"


def _market(group_name: str, selections: list[dict], name: str | None = None) -> dict:
    return {"marketGroupName": group_name, "name": name or group_name, "selections": selections}


def test_two_way_btts():
    raw = _market("Ambos equipos marcarán", [
        _selection("Sí", 4, 6, 10),
        _selection("No", 21, 20, 20),
    ])
    market = _two_way(raw, EVENT_NAME, "BTTS", {"Sí": "Yes", "No": "No"})
    assert market is not None
    assert market.market_type == "BTTS"
    assert [(o.name, round(o.odds, 2)) for o in market.outcomes] == [("Yes", 1.67), ("No", 2.05)]


def test_two_way_rejects_wrong_selection_count():
    raw = _market("Ambos equipos marcarán", [_selection("Sí", 4, 6, 10)])
    assert _two_way(raw, EVENT_NAME, "BTTS", {"Sí": "Yes", "No": "No"}) is None


def test_team_two_way_dnb():
    raw = _market("Victoria sin empate (en caso de empate se anula la apuesta)", [
        _selection(HOME, 3, 10, 10),
        _selection(AWAY, 3, 1, 30),
    ])
    market = _team_two_way(raw, EVENT_NAME, "DNB", HOME, AWAY)
    assert market is not None
    assert market.market_type == "DNB"
    assert [(o.name, round(o.odds, 2)) for o in market.outcomes] == [("1", 1.3), ("2", 4.0)]


def test_team_two_way_ignores_unknown_selection_name():
    raw = _market("Victoria sin empate (en caso de empate se anula la apuesta)", [
        _selection(HOME, 3, 10, 10),
        _selection("Un tercer equipo", 3, 1, 30),
    ])
    assert _team_two_way(raw, EVENT_NAME, "DNB", HOME, AWAY) is None


def test_three_way_half_time_1x2():
    raw = _market("Apuestas al 1er Tiempo", [
        _selection(HOME, 6, 5, 10),
        _selection("Empate", 5, 4, 20),
        _selection(AWAY, 18, 5, 30),
    ])
    market = _three_way(raw, EVENT_NAME, "1X2_HT", HOME, AWAY)
    assert market is not None
    assert market.market_type == "1X2_HT"
    assert [(o.name, round(o.odds, 2)) for o in market.outcomes] == [("1", 2.2), ("X", 2.25), ("2", 4.6)]


def test_double_chance_from_free_text_selections():
    raw = _market(
        "Doble oportunidad (Predecir la combinación de 2 resultados posibles de un partido)",
        [
            _selection(f"{HOME} o Empate", 4, 25, 10),
            _selection(f"{HOME} o {AWAY}", 1, 3, 20),
            _selection(f"{AWAY} o Empate", 5, 4, 30),
        ],
    )
    market = _double_chance(raw, EVENT_NAME, HOME, AWAY)
    assert market is not None
    assert market.market_type == "DC"
    assert {o.name for o in market.outcomes} == {"1X", "12", "X2"}
    by_label = {o.name: round(o.odds, 2) for o in market.outcomes}
    assert by_label == {"1X": 1.16, "12": 1.33, "X2": 2.25}


def test_double_chance_rejects_unmatched_text():
    # Un texto que no encaja con ningún par 1/X/2 (p.ej. por un cambio de
    # formato en la web) no debe fabricar un mercado a medias.
    raw = _market("Doble oportunidad (...)", [
        _selection(f"{HOME} o Empate", 4, 25, 10),
        _selection(f"{HOME} o {AWAY}", 1, 3, 20),
        _selection("Texto inesperado", 5, 4, 30),
    ])
    assert _double_chance(raw, EVENT_NAME, HOME, AWAY) is None


def test_over_under_lines_groups_by_line_and_skips_incomplete():
    raw = _market("Total Match Goals Over/Under Goals Static", [
        _selection("Más de 0.5", 1, 25, 10),
        _selection("Menos de 0.5", 19, 2, 10),
        _selection("Más de 2.5", 19, 20, 20),
        _selection("Menos de 2.5", 15, 20, 20),
        # Línea suspendida (status "S"): descartada por _decimal_odds, no debe
        # colarse como mercado incompleto.
        _selection("Más de 10.5", 1, 111, 30, status="S"),
    ])
    markets = _over_under_lines(raw, EVENT_NAME, "")
    types = {m.market_type for m in markets}
    assert types == {"OU_0.5", "OU_2.5"}
    ou_25 = next(m for m in markets if m.market_type == "OU_2.5")
    assert [(o.name, round(o.odds, 2)) for o in ou_25.outcomes] == [("Over", 1.95), ("Under", 1.75)]


def test_over_under_lines_applies_period_suffix():
    raw = _market("1st Half Over/Under Goals Static", [
        _selection("Más de 1.5", 6, 4, 10),
        _selection("Menos de 1.5", 5, 1, 20),
    ])
    markets = _over_under_lines(raw, EVENT_NAME, "_HT")
    assert [m.market_type for m in markets] == ["OU_HT_1.5"]


def test_all_markets_flattens_flat_and_grouped():
    detail = {
        "markets": [{"marketGroupName": "Ambos equipos marcarán"}],
        "groupedMarkets": [
            {"name": "Resultado del partido", "markets": [{"marketGroupName": "Doble oportunidad (...)"}]},
            {"name": "Más/Menos goles", "markets": [{"marketGroupName": "Total Match Goals Over/Under Goals Static"}]},
        ],
    }
    names = {m["marketGroupName"] for m in _all_markets(detail)}
    assert names == {"Ambos equipos marcarán", "Doble oportunidad (...)", "Total Match Goals Over/Under Goals Static"}


def test_parse_extra_markets_end_to_end():
    # Ficha de partido realista: la colección "Popular" trae DC/BTTS/DNB/OU
    # (grupo "Resultado del partido" y "Más/Menos goles"), sin 1X2_HT.
    detail = {
        "markets": [
            _market("Ambos equipos marcarán", [_selection("Sí", 4, 6, 10), _selection("No", 21, 20, 20)]),
            _market("Victoria sin empate (en caso de empate se anula la apuesta)", [
                _selection(HOME, 3, 10, 10), _selection(AWAY, 3, 1, 30),
            ]),
            # Mercado irrelevante (goleadores...): debe ignorarse sin fallar.
            _market("Primer goleador", [_selection("Un jugador", 3, 1, 10)]),
        ],
        "groupedMarkets": [
            {
                "name": "Resultado del partido",
                "markets": [_market(
                    "Doble oportunidad (...)",
                    [
                        _selection(f"{HOME} o Empate", 4, 25, 10),
                        _selection(f"{HOME} o {AWAY}", 1, 3, 20),
                        _selection(f"{AWAY} o Empate", 5, 4, 30),
                    ],
                )],
            },
            {
                "name": "Más/Menos goles",
                "markets": [_market("Total Match Goals Over/Under Goals Static", [
                    _selection("Más de 2.5", 19, 20, 10), _selection("Menos de 2.5", 15, 20, 20),
                ])],
            },
        ],
    }
    markets = parse_extra_markets(detail, EVENT_NAME, HOME, AWAY)
    types = {m.market_type for m in markets}
    assert types == {"BTTS", "DNB", "DC", "OU_2.5"}
    assert all(m.event == EVENT_NAME for m in markets)


def test_parse_extra_markets_deduplicates_by_market_type():
    # La API a veces repite el mismo marketGroupName dos veces en la misma
    # respuesta (visto en vivo con "Apuestas al 1er Tiempo"): solo debe
    # quedarse con el primero, no fabricar un mercado duplicado.
    ht_market = _market("Apuestas al 1er Tiempo", [
        _selection(HOME, 6, 5, 10), _selection("Empate", 5, 4, 20), _selection(AWAY, 18, 5, 30),
    ])
    detail = {"markets": [ht_market, ht_market], "groupedMarkets": []}
    markets = parse_extra_markets(detail, EVENT_NAME, HOME, AWAY)
    assert [m.market_type for m in markets] == ["1X2_HT"]
