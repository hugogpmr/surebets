"""Baloncesto y tenis en Altenar/Kambi (añadidos 2026-09-24, ver README).

Fixtures basadas en respuestas reales capturadas en vivo (GetAllSports confirmó
sportId 67/68; ver providers/altenar.py y providers/kambi.py para el detalle).
"""

from providers.altenar import _quarter_number, parse_event_markets
from providers.filters import is_excluded
from providers.kambi import parse_event_offers


def test_womens_filter_only_applies_to_football_not_basketball_or_tennis():
    # WNBA/WTA son producto mayoritario, con nombres consistentes entre
    # plataformas (a diferencia del fútbol femenino) - no hay motivo para
    # perder esa cobertura por defecto.
    wnba_labels = ["WNBA", "NYL Liberty (F)", "ATL Dream (F)"]
    assert is_excluded(wnba_labels, exclude_esports=True, exclude_women=True, sport="futbol") is True
    assert is_excluded(wnba_labels, exclude_esports=True, exclude_women=True, sport="baloncesto") is False
    assert is_excluded(wnba_labels, exclude_esports=True, exclude_women=True, sport="tenis") is False
    # El filtro de esports sigue aplicando a cualquier deporte.
    assert is_excluded(["E-battles", "A (bot1)", "B (bot2)"], exclude_esports=True, exclude_women=False, sport="baloncesto") is True

# --- Altenar: tenis y baloncesto ------------------------------------------------

HOME, AWAY = 10, 20


def _odd(odd_id, name, price, status=0, team=None):
    return {"id": odd_id, "name": name, "price": price, "oddStatus": status, "typeId": 0, "competitorId": team}


def _market(market_id, type_id, odd_ids, name=""):
    return {"id": market_id, "typeId": type_id, "isBB": False, "desktopOddIds": [odd_ids], "name": name}


def _by_type(markets):
    return {m.market_type: m for m in markets}


TENNIS_DETAILS = {
    "competitors": [{"id": HOME, "name": "Player A"}, {"id": AWAY, "name": "Player B"}],
    "odds": [
        _odd(1, "Player A", 1.5, team=HOME),
        _odd(2, "Player B", 2.5, team=AWAY),
        _odd(3, "Más de 22.5", 1.9),
        _odd(4, "Menos de 22.5", 1.9),
        _odd(5, "Impar", 1.9),
        _odd(6, "Par", 1.9),
        _odd(7, "Player A (-2.5)", 1.8, team=HOME),
        _odd(8, "Player B (+2.5)", 2.0, team=AWAY),
        _odd(9, "Player A", 1.6, team=HOME),
        _odd(10, "Player B", 2.3, team=AWAY),
    ],
    "markets": [
        _market(1, 186, [1, 2]),  # Ganador
        _market(2, 189, [3, 4]),  # Total de juegos
        _market(3, 198, [5, 6]),  # Juegos par/impar
        _market(4, 187, [7, 8]),  # Hándicap de juegos
        _market(5, 202, [9, 10]),  # Ganador del primer set
    ],
}


def test_tennis_winner_uses_competitor_id_like_football_1x2():
    types = _by_type(parse_event_markets(TENNIS_DETAILS, "Player A vs. Player B", "tenis", "jokerbet"))
    assert [(o.name, o.odds) for o in types["ML"].outcomes] == [("1", 1.5), ("2", 2.5)]
    assert [(o.name, o.odds) for o in types["ML_SET1"].outcomes] == [("1", 1.6), ("2", 2.3)]


def test_tennis_totals_odd_even_and_handicap_reuse_football_parsing():
    types = _by_type(parse_event_markets(TENNIS_DETAILS, "Player A vs. Player B", "tenis", "jokerbet"))
    assert {o.name for o in types["OU_22.5"].outcomes} == {"Over", "Under"}
    assert [(o.name, o.odds) for o in types["OE"].outcomes] == [("Odd", 1.9), ("Even", 1.9)]
    assert [(o.name, o.odds) for o in types["AH_-2.5"].outcomes] == [("1", 1.8), ("2", 2.0)]


BASKETBALL_DETAILS = {
    "competitors": [{"id": HOME, "name": "Team A"}, {"id": AWAY, "name": "Team B"}],
    "odds": [
        _odd(1, "Team A", 1.4, team=HOME),
        _odd(2, "Team B", 3.0, team=AWAY),
        _odd(3, "Sí", 6.5),
        _odd(4, "No", 1.05),
        # Cuarto 1 y cuarto 2 comparten typeId 236: solo el nombre del mercado los distingue
        _odd(10, "Más de 41.5", 1.9),
        _odd(11, "Menos de 41.5", 1.9),
        _odd(12, "Más de 42.5", 1.9),
        _odd(13, "Menos de 42.5", 1.9),
        # DNB del primer cuarto (típico "apuesta sin empate"), equipo por competitorId
        _odd(20, "Team A", 1.9, team=HOME),
        _odd(21, "Team B", 1.9, team=AWAY),
    ],
    "markets": [
        _market(1, 219, [1, 2]),  # Ganador (incl. prórroga)
        _market(2, 220, [3, 4]),  # Habrá prórroga
        _market(3, 236, [10, 11], name="Primer Cuarto  - Totales"),
        _market(4, 236, [12, 13], name="Segundo Cuarto  - Totales"),
        _market(5, 302, [20, 21], name="Primer cuarto - apuesta sin empate"),
    ],
}


def test_basketball_winner_and_overtime_yes_no():
    types = _by_type(parse_event_markets(BASKETBALL_DETAILS, "Team A vs. Team B", "baloncesto", "jokerbet"))
    assert [(o.name, o.odds) for o in types["ML"].outcomes] == [("1", 1.4), ("2", 3.0)]
    assert [(o.name, o.odds) for o in types["OT"].outcomes] == [("Yes", 6.5), ("No", 1.05)]


def test_basketball_quarter_reused_type_id_is_disambiguated_by_market_name():
    types = _by_type(parse_event_markets(BASKETBALL_DETAILS, "Team A vs. Team B", "baloncesto", "jokerbet"))
    assert {o.name for o in types["OU_Q1_41.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in types["OU_Q2_42.5"].outcomes} == {"Over", "Under"}
    assert [(o.name, o.odds) for o in types["DNB_Q1"].outcomes] == [("1", 1.9), ("2", 1.9)]


def test_quarter_number_recognizes_both_ordinal_formats_seen_live():
    assert _quarter_number("Primer Cuarto  - Totales") == 1
    assert _quarter_number("Segundo cuarto - apuesta sin empate") == 2
    assert _quarter_number("3° cuarto - hándicap") == 3
    assert _quarter_number("Cuarto cuarto - par/impar") == 4
    assert _quarter_number("1ª Mitad - total") is None
    assert _quarter_number("Margen de victoria") is None


def test_unmatched_quarter_market_name_is_dropped_instead_of_guessed():
    details = {
        "competitors": BASKETBALL_DETAILS["competitors"],
        "odds": BASKETBALL_DETAILS["odds"],
        "markets": [_market(1, 236, [10, 11], name="Totales del partido")],  # texto inesperado, sin ordinal
    }
    assert parse_event_markets(details, "Team A vs. Team B", "baloncesto", "jokerbet") == []


# --- Kambi: tenis y baloncesto ---------------------------------------------------

K_HOME, K_AWAY = "Player A", "Player B"


def _k_outcome(kind, odds, line=None, participant=None, status="OPEN"):
    return {"type": kind, "odds": odds, "line": line, "participant": participant, "status": status}


def _k_offer(label, offer_type, outcomes):
    return {"criterion": {"englishLabel": label}, "betOfferType": {"englishName": offer_type}, "outcomes": outcomes}


TENNIS_OFFERS = {
    "betOffers": [
        _k_offer("Match Odds", "Match", [_k_outcome("OT_ONE", 1500, participant=K_HOME), _k_outcome("OT_TWO", 2500, participant=K_AWAY)]),
        _k_offer("Set 1", "Match", [_k_outcome("OT_ONE", 1600, participant=K_HOME), _k_outcome("OT_TWO", 2300, participant=K_AWAY)]),
        _k_offer("Game Handicap", "Handicap", [_k_outcome("OT_ONE", 1800, -2500, K_HOME), _k_outcome("OT_TWO", 2000, 2500, K_AWAY)]),
        _k_offer("Set Handicap", "Handicap", [_k_outcome("OT_ONE", 1530, -1500, K_HOME), _k_outcome("OT_TWO", 2430, 1500, K_AWAY)]),
        _k_offer("Total Games", "Over/Under", [_k_outcome("OT_OVER", 1900, 22500), _k_outcome("OT_UNDER", 1900, 22500)]),
        _k_offer("Total Games - Set 1", "Over/Under", [_k_outcome("OT_OVER", 1850, 9500), _k_outcome("OT_UNDER", 1950, 9500)]),
        _k_offer("Total Sets", "Over/Under", [_k_outcome("OT_OVER", 2350, 2500), _k_outcome("OT_UNDER", 1570, 2500)]),
        _k_offer("Total games won by Player A", "Over/Under", [_k_outcome("OT_OVER", 1530, 7500), _k_outcome("OT_UNDER", 2400, 7500)]),
    ]
}


def test_kambi_tennis_match_and_set_winner_use_two_way_mapping():
    markets, _ = _parse_tennis()
    assert [(o.name, o.odds) for o in markets["ML"].outcomes] == [("1", 1.5), ("2", 2.5)]
    assert [(o.name, o.odds) for o in markets["ML_SET1"].outcomes] == [("1", 1.6), ("2", 2.3)]


def test_kambi_tennis_handicaps_and_totals():
    markets, _ = _parse_tennis()
    assert [(o.name, o.odds) for o in markets["AH_-2.5"].outcomes] == [("1", 1.8), ("2", 2.0)]
    assert [(o.name, o.odds) for o in markets["SETS_AH_-1.5"].outcomes] == [("1", 1.53), ("2", 2.43)]
    assert {o.name for o in markets["OU_22.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in markets["OU_SET1_9.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in markets["SETS_OU_2.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in markets["OU_HOME_7.5"].outcomes} == {"Over", "Under"}


def _parse_tennis(bookmaker="paf"):
    markets = parse_event_offers(TENNIS_OFFERS, "Player A vs. Player B", "tenis", bookmaker, K_HOME, K_AWAY)
    return {m.market_type: m for m in markets}, markets


B_HOME, B_AWAY = "Team A", "Team B"

BASKETBALL_OFFERS = {
    "betOffers": [
        _k_offer("Moneyline - Including Overtime", "Match", [_k_outcome("OT_ONE", 1400, participant=B_HOME), _k_outcome("OT_TWO", 3000, participant=B_AWAY)]),
        _k_offer("Point Spread - Including Overtime", "Handicap", [_k_outcome("OT_ONE", 1900, -9500, B_HOME), _k_outcome("OT_TWO", 1900, 9500, B_AWAY)]),
        _k_offer("Total Points - Including Overtime", "Over/Under", [_k_outcome("OT_OVER", 1900, 179500), _k_outcome("OT_UNDER", 1900, 179500)]),
        _k_offer("Total Points Odd/Even - Including Overtime", "Odd/Even", [_k_outcome("OT_ODD", 1900), _k_outcome("OT_EVEN", 1900)]),
        _k_offer("Draw No Bet - Quarter 1", "Match", [_k_outcome("OT_ONE", 1900, participant=B_HOME), _k_outcome("OT_TWO", 1900, participant=B_AWAY)]),
        _k_offer("Handicap - Quarter 1", "Handicap", [_k_outcome("OT_ONE", 1900, -2500, B_HOME), _k_outcome("OT_TWO", 1900, 2500, B_AWAY)]),
        _k_offer("Total Points - Quarter 1", "Over/Under", [_k_outcome("OT_OVER", 1900, 41500), _k_outcome("OT_UNDER", 1900, 41500)]),
        _k_offer("Total Points by Team A - 1st Half", "Over/Under", [_k_outcome("OT_OVER", 1900, 40500), _k_outcome("OT_UNDER", 1900, 40500)]),
    ]
}


def _parse_basketball(bookmaker="paf"):
    markets = parse_event_offers(BASKETBALL_OFFERS, "Team A vs. Team B", "baloncesto", bookmaker, B_HOME, B_AWAY)
    return {m.market_type: m for m in markets}, markets


def test_kambi_basketball_full_match_markets_incl_overtime():
    markets, _ = _parse_basketball()
    assert [(o.name, o.odds) for o in markets["ML"].outcomes] == [("1", 1.4), ("2", 3.0)]
    assert [(o.name, o.odds) for o in markets["AH_-9.5"].outcomes] == [("1", 1.9), ("2", 1.9)]
    assert {o.name for o in markets["OU_179.5"].outcomes} == {"Over", "Under"}
    assert [(o.name, o.odds) for o in markets["OE"].outcomes] == [("Odd", 1.9), ("Even", 1.9)]


def test_kambi_basketball_quarter_and_half_suffixes():
    markets, _ = _parse_basketball()
    assert [(o.name, o.odds) for o in markets["DNB_Q1"].outcomes] == [("1", 1.9), ("2", 1.9)]
    assert [(o.name, o.odds) for o in markets["AH_Q1_-2.5"].outcomes] == [("1", 1.9), ("2", 1.9)]
    assert {o.name for o in markets["OU_Q1_41.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in markets["OU_HOME_HT_40.5"].outcomes} == {"Over", "Under"}


def test_kambi_fetch_markets_ignores_unsupported_sport_without_network():
    from providers.kambi import KambiProvider

    assert KambiProvider().fetch_markets(["balonmano_champions"]) == []


def test_altenar_fetch_markets_ignores_unsupported_sport_without_network():
    from providers.altenar import AltenarProvider

    assert AltenarProvider().fetch_markets(["balonmano_champions"]) == []
