from providers.betfair_exchange import (
    BetfairExchangeProvider,
    _best_back,
    _net_odds,
    _parse_match_odds,
)

# Forma real de listMarketCatalogue/listMarketBook según la documentación
# oficial de Betfair API-NG (no se ha podido verificar en vivo, ver docstring
# del módulo): listMarketCatalogue trae nombres, listMarketBook trae precios,
# cruzados por selectionId.
CATALOGUE_ENTRY = {
    "marketId": "1.234567890",
    "event": {"id": "31234567", "name": "Barcelona v Getafe"},
    "competition": {"id": "117", "name": "Spanish La Liga"},
    "runners": [
        {"selectionId": 111, "runnerName": "Barcelona"},
        {"selectionId": 222, "runnerName": "Getafe"},
        {"selectionId": 333, "runnerName": "The Draw"},
    ],
}

BOOK = {
    "marketId": "1.234567890",
    "runners": [
        {"selectionId": 111, "status": "ACTIVE", "ex": {"availableToBack": [{"price": 1.10, "size": 500}]}},
        {"selectionId": 222, "status": "ACTIVE", "ex": {"availableToBack": [{"price": 21.0, "size": 200}]}},
        {"selectionId": 333, "status": "ACTIVE", "ex": {"availableToBack": [{"price": 11.5, "size": 100}]}},
    ],
}


def test_net_odds_discounts_commission_from_net_winnings_only():
    # Cuota 2.00 con 5% de comisión: la ganancia neta (1.00) se queda en 0.95,
    # así que la cuota equivalente es 1.95, no 1.90 (eso descontaría del total).
    assert _net_odds(2.00, 0.05) == 1.95


def test_best_back_applies_commission_and_ignores_inactive_runners():
    runner = {"status": "ACTIVE", "ex": {"availableToBack": [{"price": 2.00, "size": 50}]}}
    assert _best_back(runner, 0.05) == 1.95
    assert _best_back({"status": "SUSPENDED", "ex": {"availableToBack": [{"price": 2.0}]}}, 0.05) is None
    assert _best_back({"status": "ACTIVE", "ex": {"availableToBack": []}}, 0.05) is None
    assert _best_back(None, 0.05) is None


def test_parses_match_odds_matching_runners_by_selection_id_and_event_name():
    market = _parse_match_odds(CATALOGUE_ENTRY, BOOK, commission=0.05)

    assert market is not None
    assert market.event == "Barcelona vs. Getafe"
    assert market.market_type == "1X2"
    assert market.sport == "futbol"
    outcomes = {o.name: o.odds for o in market.outcomes}
    assert outcomes["1"] == _net_odds(1.10, 0.05)
    assert outcomes["X"] == _net_odds(11.5, 0.05)
    assert outcomes["2"] == _net_odds(21.0, 0.05)
    assert all(o.bookmaker == "betfair_exchange" for o in market.outcomes)


def test_falls_back_to_runner_order_when_names_dont_match_event_name():
    catalogue = dict(CATALOGUE_ENTRY, event={"id": "x", "name": "FC Foo v FC Bar"})
    market = _parse_match_odds(catalogue, BOOK, commission=0.05)
    assert market is not None
    assert market.event == "FC Foo vs. FC Bar"
    # Sin poder casar por nombre, usa el orden de listMarketCatalogue (111, 222 = 1/2).
    outcomes = {o.name: o.odds for o in market.outcomes}
    assert outcomes["1"] == _net_odds(1.10, 0.05)
    assert outcomes["2"] == _net_odds(21.0, 0.05)


def test_returns_none_without_a_draw_runner():
    catalogue = dict(CATALOGUE_ENTRY, runners=[
        {"selectionId": 1, "runnerName": "A"},
        {"selectionId": 2, "runnerName": "B"},
    ])
    assert _parse_match_odds(catalogue, BOOK, commission=0.05) is None


def test_returns_none_when_a_price_is_missing():
    book = {"marketId": "1.234567890", "runners": [BOOK["runners"][0], BOOK["runners"][1]]}
    assert _parse_match_odds(CATALOGUE_ENTRY, book, commission=0.05) is None


def test_fetch_markets_noop_without_credentials():
    provider = BetfairExchangeProvider(app_key="", username="", password="")
    assert provider.fetch_markets(["futbol"]) == []


def test_fetch_markets_noop_for_non_football_sports():
    provider = BetfairExchangeProvider(app_key="k", username="u", password="p")
    assert provider.fetch_markets(["tenis"]) == []
