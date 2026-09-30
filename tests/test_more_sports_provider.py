"""Hockey hielo, béisbol, balonmano y voleibol en Altenar/Kambi (añadidos 2026-09-29).

Fixtures con la forma de las respuestas reales capturadas ese día (GetEventDetails de Jokerbet,
betoffer/event de Paf): nombres de mercado y de resultado tal cual, precios recortados.
"""

from providers.altenar import _period_number, parse_event_markets
from providers.kambi import parse_event_offers

HOME, AWAY = 10, 20


def _odd(odd_id, name, price, team=None, status=0):
    return {"id": odd_id, "name": name, "price": price, "oddStatus": status, "typeId": 0, "competitorId": team}


def _market(market_id, type_id, odd_ids, name=""):
    return {"id": market_id, "typeId": type_id, "isBB": False, "desktopOddIds": [odd_ids], "name": name}


def _by_type(markets):
    return {m.market_type: m for m in markets}


def _pairs(market):
    return {o.name: o.odds for o in market.outcomes}


# --- Altenar: hockey -------------------------------------------------------------

HOCKEY = {
    "competitors": [{"id": HOME, "name": "TOR Maple Leafs"}, {"id": AWAY, "name": "MTL Canadiens"}],
    "odds": [
        _odd(1, "TOR Maple Leafs", 1.92, HOME), _odd(2, "MTL Canadiens", 1.88, AWAY),  # 406 ganador incl. prórroga
        _odd(3, "Más de 6.5", 1.88), _odd(4, "Menos de 6.5", 1.85),  # 412 total incl. prórroga
        _odd(5, "Más de 5.5", 1.7), _odd(6, "Menos de 5.5", 2.1),  # 18 total reglamentario
        _odd(7, "Sí", 1.05), _odd(8, "No", 7.5),  # 29 ambos marcan (reglamentario)
        _odd(9, "TOR Maple Leafs", 2.7, HOME), _odd(10, "Empate", 2.8), _odd(11, "MTL Canadiens", 2.6, AWAY),  # 1x2 periodo
        _odd(12, "Más de 1.5", 1.72), _odd(13, "Menos de 1.5", 2.0),  # total del 2º periodo
        _odd(14, "TOR Maple Leafs", 2.1, HOME), _odd(15, "Empate", 2.9), _odd(16, "MTL Canadiens", 2.9, AWAY),  # 1x2 3er periodo
    ],
    "markets": [
        _market(1, 406, [1, 2], "Ganador (incl. prórroga y penaltis)"),
        _market(2, 412, [3, 4], "Totales (incl. prórroga y penaltis)"),
        _market(3, 18, [5, 6], "Total"),
        _market(4, 29, [7, 8], "Ambos equipos marcan"),
        _market(5, 443, [9, 10, 11], "Primero periodo - 1x2"),
        _market(6, 446, [12, 13], "Segundo periodo - total"),
        _market(7, 443, [14, 15, 16], "Tercero periodo - 1x2"),
        _market(8, 199, [1, 2], "Marcador exacto"),  # sin spec: se ignora
    ],
}


def test_altenar_hockey_full_match_markets_keep_overtime_apart_from_regulation_time():
    types = _by_type(parse_event_markets(HOCKEY, "TOR Maple Leafs vs. MTL Canadiens", "hockey", "jokerbet"))
    assert _pairs(types["ML"]) == dict([("1", 1.92), ("2", 1.88)])
    assert {o.name for o in types["OU_6.5"].outcomes} == {"Over", "Under"}  # incl. prórroga: sin sufijo
    assert {o.name for o in types["OU_REG_5.5"].outcomes} == {"Over", "Under"}  # reglamentario: con sufijo
    assert _pairs(types["BTTS_REG"]) == dict([("Yes", 1.05), ("No", 7.5)])
    assert "BTTS" not in types and "OU_5.5" not in types


def test_altenar_hockey_period_markets_are_told_apart_by_the_period_in_the_name():
    types = _by_type(parse_event_markets(HOCKEY, "TOR Maple Leafs vs. MTL Canadiens", "hockey", "jokerbet"))
    assert _pairs(types["1X2_P1"]) == dict([("1", 2.7), ("X", 2.8), ("2", 2.6)])
    assert _pairs(types["1X2_P3"]) == dict([("1", 2.1), ("X", 2.9), ("2", 2.9)])
    assert {o.name for o in types["OU_P2_1.5"].outcomes} == {"Over", "Under"}


def test_altenar_hockey_period_market_with_unreadable_name_is_dropped():
    details = {**HOCKEY, "markets": [_market(1, 443, [9, 10, 11], "Periodo extra - 1x2")]}
    assert parse_event_markets(details, "A vs. B", "hockey", "jokerbet") == []


def test_period_number_reads_both_ordinal_spellings():
    assert _period_number("Primero periodo - 1x2") == 1
    assert _period_number("Primer periodo - total") == 1
    assert _period_number("Segundo periodo - par/impar") == 2
    assert _period_number("Tercero periodo - doble oportunidad") == 3
    assert _period_number("Tercer periodo - primer gol") == 3
    assert _period_number("Ganador (incl. prórroga y penaltis)") is None


# --- Altenar: béisbol, balonmano, voleibol --------------------------------------

BASEBALL = {
    "competitors": [{"id": HOME, "name": "NY Yankees"}, {"id": AWAY, "name": "BOS Red Sox"}],
    "odds": [
        _odd(1, "NY Yankees", 1.77, HOME), _odd(2, "BOS Red Sox", 2.1, AWAY),
        _odd(3, "NY Yankees (-1.5)", 2.15, HOME), _odd(4, "BOS Red Sox (+1.5)", 1.65, AWAY),
        _odd(5, "Más de 8.5", 1.9), _odd(6, "Menos de 8.5", 1.9),
        _odd(7, "Más de 4.5", 1.8), _odd(8, "Menos de 4.5", 2.0),  # 5 primeros innings
        _odd(9, "Más de 4.5", 1.85), _odd(10, "Menos de 4.5", 1.95),  # total del local
    ],
    "markets": [
        _market(1, 251, [1, 2], "Ganador (incl. extra innings)"),
        _market(2, 256, [3, 4], "Hándicap (incl. extra innings)"),
        _market(3, 258, [5, 6], "Totales (incl. extra innings)"),
        _market(4, 276, [7, 8], "Innings 1 a 5 - Total"),
        _market(5, 260, [9, 10], "NY Yankees Más de/Menos de (incl. extra innings)"),
        _market(6, 262, [5, 6], "Total (más de-exacto-menos de) (incl. extra innings)"),  # sin spec
    ],
}


def test_altenar_baseball_markets():
    types = _by_type(parse_event_markets(BASEBALL, "NY Yankees vs. BOS Red Sox", "beisbol", "jokerbet"))
    assert _pairs(types["ML"]) == dict([("1", 1.77), ("2", 2.1)])
    assert {o.name for o in types["OU_8.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in types["OU_F5_4.5"].outcomes} == {"Over", "Under"}
    assert {o.name for o in types["OU_HOME_4.5"].outcomes} == {"Over", "Under"}
    assert any(t.startswith("AH_-1.5") for t in types)


def test_altenar_handball_has_a_draw_in_the_full_time_result():
    details = {
        "competitors": [{"id": HOME, "name": "A"}, {"id": AWAY, "name": "B"}],
        "odds": [_odd(1, "A", 1.5, HOME), _odd(2, "Empate", 7.5), _odd(3, "B", 3.0, AWAY),
                 _odd(4, "A", 1.4, HOME), _odd(5, "B", 2.5, AWAY)],
        "markets": [_market(1, 1, [1, 2, 3], "1x2"), _market(2, 11, [4, 5], "Apuesta sin empate")],
    }
    types = _by_type(parse_event_markets(details, "A vs. B", "balonmano", "jokerbet"))
    assert _pairs(types["1X2"]) == dict([("1", 1.5), ("X", 7.5), ("2", 3.0)])
    assert _pairs(types["DNB"]) == dict([("1", 1.4), ("2", 2.5)])


def test_altenar_volleyball_winner_and_total_points():
    details = {
        "competitors": [{"id": HOME, "name": "A"}, {"id": AWAY, "name": "B"}],
        "odds": [_odd(1, "A", 2.1, HOME), _odd(2, "B", 1.67, AWAY), _odd(3, "Más de 142.5", 1.83), _odd(4, "Menos de 142.5", 1.83)],
        "markets": [_market(1, 186, [1, 2], "Ganador"), _market(2, 238, [3, 4], "Total puntos")],
    }
    types = _by_type(parse_event_markets(details, "A vs. B", "voleibol", "jokerbet"))
    assert _pairs(types["ML"]) == dict([("1", 2.1), ("2", 1.67)])
    assert {o.name for o in types["OU_142.5"].outcomes} == {"Over", "Under"}


# --- Kambi ----------------------------------------------------------------------

K_HOME, K_AWAY = "Toronto Maple Leafs", "Montreal Canadiens"


def _k_outcome(kind, odds, line=None, participant=None, status="OPEN"):
    return {"type": kind, "odds": odds, "line": line, "participant": participant, "status": status}


def _k_offer(label, offer_type, outcomes):
    return {"criterion": {"englishLabel": label}, "betOfferType": {"englishName": offer_type}, "outcomes": outcomes}


def _two_way(label, offer_type="Match"):
    return _k_offer(label, offer_type, [_k_outcome("OT_ONE", 1900, participant=K_HOME), _k_outcome("OT_TWO", 1900, participant=K_AWAY)])


def _totals(label, line):
    return _k_offer(label, "Over/Under", [_k_outcome("OT_OVER", 1900, line), _k_outcome("OT_UNDER", 1900, line)])


HOCKEY_OFFERS = {
    "betOffers": [
        _two_way("Moneyline - Including Overtime and penalty shootout"),
        _k_offer("Puck Line - Including Overtime and Penalty Shootout", "Handicap",
                 [_k_outcome("OT_ONE", 2500, -1500, K_HOME), _k_outcome("OT_TWO", 1500, 1500, K_AWAY)]),
        _totals("Total Goals - Including Overtime and Penalty Shootout", 6500),
        _totals("Total Goals - Regular Time", 5500),
        _totals("Total Goals by Toronto Maple Leafs - Regular Time", 3500),
        _totals("Total Goals - Period 1", 1500),
        _k_offer("Both Teams To Score - Regular Time", "Yes/No", [_k_outcome("OT_YES", 1100), _k_outcome("OT_NO", 6500)]),
        _k_offer("Period 2", "Match", [_k_outcome("OT_ONE", 2700), _k_outcome("OT_CROSS", 2800), _k_outcome("OT_TWO", 2600)]),
        _k_offer("Match Odds - Regular Time", "Match", [_k_outcome("OT_ONE", 2400), _k_outcome("OT_CROSS", 4200), _k_outcome("OT_TWO", 2500)]),
        _totals("Total Shots on Goal - Including Overtime", 55500),  # sin equivalente: se ignora
    ]
}


def test_kambi_hockey_uses_the_same_prefixes_as_altenar():
    markets = _by_type(parse_event_offers(HOCKEY_OFFERS, f"{K_HOME} vs. {K_AWAY}", "hockey", "paf", K_HOME, K_AWAY))
    assert _pairs(markets["ML"]) == dict([("1", 1.9), ("2", 1.9)])
    assert "AH_-1.5" in markets
    assert "OU_6.5" in markets  # partido completo: como el 412 de Altenar
    assert "OU_REG_5.5" in markets and "OU_HOME_REG_3.5" in markets
    assert "OU_P1_1.5" in markets and "BTTS_REG" in markets
    assert _pairs(markets["1X2_P2"]) == dict([("1", 2.7), ("X", 2.8), ("2", 2.6)])
    assert not any("55.5" in t for t in markets)  # tiros a puerta: no es un mercado que crucemos
    assert not any(t in ("1X2", "ML_REG") for t in markets)  # el 1X2 reglamentario 3 vías no se emite como ML


BASEBALL_OFFERS = {
    "betOffers": [
        _two_way("Moneyline"),
        _k_offer("Run Line", "Handicap", [_k_outcome("OT_ONE", 2100, -1500, K_HOME), _k_outcome("OT_TWO", 1700, 1500, K_AWAY)]),
        _totals("Total Runs", 9500),
        _totals("Total Runs - First 5 Innings", 4500),
        _totals("Total Runs - Inning 1", 500),
        _totals("Total Runs by Toronto Maple Leafs", 4500),
        _k_offer("Total Runs Odd/Even", "Odd/Even", [_k_outcome("OT_ODD", 1900), _k_outcome("OT_EVEN", 1900)]),
        _totals("Total Hits", 15500),  # sin equivalente
    ]
}


def test_kambi_baseball_markets():
    markets = _by_type(parse_event_offers(BASEBALL_OFFERS, f"{K_HOME} vs. {K_AWAY}", "beisbol", "paf", K_HOME, K_AWAY))
    assert "ML" in markets and "AH_-1.5" in markets and "OU_9.5" in markets
    assert "OU_F5_4.5" in markets and "OU_I1_0.5" in markets and "OU_HOME_4.5" in markets
    assert _pairs(markets["OE"]) == dict([("Odd", 1.9), ("Even", 1.9)])
    assert not any("15.5" in t for t in markets)


def test_kambi_handball_first_half_and_odd_even():
    offers = {
        "betOffers": [
            _k_offer("Full Time", "Match", [_k_outcome("OT_ONE", 1500), _k_outcome("OT_CROSS", 7500), _k_outcome("OT_TWO", 3000)]),
            _k_offer("1st Half", "Match", [_k_outcome("OT_ONE", 1600), _k_outcome("OT_CROSS", 6000), _k_outcome("OT_TWO", 3200)]),
            _k_offer("Total Goals Odd/Even", "Odd/Even", [_k_outcome("OT_ODD", 1900), _k_outcome("OT_EVEN", 1900)]),
            _totals("Total Goals - 1st Half", 28500),
        ]
    }
    markets = _by_type(parse_event_offers(offers, "A vs. B", "balonmano", "paf", "A", "B"))
    assert set(markets) == {"1X2", "1X2_HT", "OE", "OU_HT_28.5"}


def test_kambi_football_labels_are_unaffected_by_the_new_period_suffixes():
    offers = {
        "betOffers": [
            _k_offer("Full Time", "Match", [_k_outcome("OT_ONE", 1500), _k_outcome("OT_CROSS", 7500), _k_outcome("OT_TWO", 3000)]),
            _totals("Total Goals - 1st Half", 1500),
            _totals("Total Goals", 2500),
        ]
    }
    markets = _by_type(parse_event_offers(offers, "A vs. B", "futbol", "paf", "A", "B"))
    assert set(markets) == {"1X2", "OU_HT_1.5", "OU_2.5"}


def test_new_sports_are_fetched_by_both_platforms():
    from providers.altenar import SPORT_IDS
    from providers.kambi import SPORT_PATHS

    for sport in ("hockey", "balonmano", "beisbol"):
        assert sport in SPORT_IDS and sport in SPORT_PATHS
    assert "voleibol" in SPORT_IDS and "voleibol" not in SPORT_PATHS  # Kambi no lo lista
