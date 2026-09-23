from datetime import datetime, timezone

from providers.williamhill import _decimal_odds, _parse_event

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
