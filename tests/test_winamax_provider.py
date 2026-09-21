from datetime import datetime, timedelta, timezone

from providers.winamax import WinamaxProvider, parse_match_state

START = datetime.now(timezone.utc) + timedelta(hours=5)


class State:
    """Estado de una ficha de Winamax (`PRELOADED_STATE`): partidos, apuestas,
    selecciones y cuotas, con la misma forma que la real (verificada en vivo el
    2026-09-21 con Alavés - Atlético Madrid)."""

    def __init__(self, status="PREMATCH", home="Alavés", away="Atlético Madrid"):
        self.data = {
            "matches": {
                "1": {
                    "matchId": 1, "status": status, "available": True, "sportId": 1, "title": f"{home} - {away}",
                    "competitor1Name": home, "competitor2Name": away, "matchStart": int(START.timestamp()),
                }
            },
            "bets": {}, "outcomes": {}, "odds": {},
        }
        self._id = 100

    def bet(self, title, selections, available=True):
        """selections = [(etiqueta, código, cuota)] o (etiqueta, código, cuota, disponible)."""
        ids = []
        for selection in selections:
            label, code, price = selection[:3]
            self._id += 1
            self.data["outcomes"][str(self._id)] = {"label": label, "code": code, "available": selection[3] if len(selection) > 3 else True}
            self.data["odds"][str(self._id)] = price
            ids.append(self._id)
        self._id += 1
        self.data["bets"][str(self._id)] = {"betId": self._id, "matchId": 1, "betTitle": title, "outcomes": ids, "available": available}
        return self

    def markets(self):
        return {m.market_type: m for m in parse_match_state(self.data, 1)}


def prices(market):
    return [(o.name, o.odds) for o in market.outcomes]


def main_state():
    return State().bet("Resultado", [("Alavés", "1", 3.6), ("Empate", "x", 3.6), ("Atl. Madrid", "2", 1.9)])


def test_one_x_two_and_event_name_and_kickoff():
    markets = main_state().markets()
    assert prices(markets["1X2"]) == [("1", 3.6), ("X", 3.6), ("2", 1.9)]
    assert markets["1X2"].event == "Alavés vs. Atlético Madrid" and markets["1X2"].start_time == datetime.fromtimestamp(int(START.timestamp()), tz=timezone.utc)
    assert all(o.bookmaker == "winamax" for o in markets["1X2"].outcomes)


def test_halves_are_suffixed_like_the_other_providers():
    state = main_state().bet("1ª mitad - Resultado", [("Alavés", "1", 4.1), ("Empate", "x", 2.2), ("Atl. Madrid", "2", 2.45)])
    state.bet("1ª mitad - Ambos equipos marcan", [("Sí", "74", 4.3), ("No", "76", 1.18)])
    markets = state.markets()
    assert prices(markets["1X2_HT"]) == [("1", 4.1), ("X", 2.2), ("2", 2.45)]
    assert prices(markets["BTTS_HT"]) == [("Yes", 4.3), ("No", 1.18)]


def test_two_way_and_double_chance_and_odd_even_and_first_goal():
    state = main_state()
    state.bet("Ganador sin empate (anulada en caso de empate)", [("Alavés", "1", 2.75), ("Atl. Madrid", "2", 1.46)])
    state.bet("Doble oportunidad", [("Alavés o empate", "9", 1.88), ("Alavés o  Atl. Madrid", "10", 1.32), ("Atl. Madrid o empate", "11", 1.29)])
    state.bet("Total de goles - Par/Impar", [("Impar", "70", 1.92), ("Par", "72", 1.8)])
    state.bet("Equipo que marca el 1er gol", [("Alavés", "6", 2.45), ("Ninguno", "7", 10.5), ("Atl. Madrid", "8", 1.68)])
    markets = state.markets()
    assert prices(markets["DNB"]) == [("1", 2.75), ("2", 1.46)]
    assert prices(markets["DC"]) == [("1X", 1.88), ("12", 1.32), ("X2", 1.29)]
    assert prices(markets["OE"]) == [("Odd", 1.92), ("Even", 1.8)]
    assert prices(markets["FIRST_GOAL"]) == [("1", 2.45), ("None", 10.5), ("2", 1.68)]


def test_totals_use_comma_lines_integer_lines_and_short_team_names():
    state = main_state()
    state.bet("Número total de goles", [("Más de 2,5", "over", 1.86), ("Menos de 2,5", "under", 1.92)])
    state.bet("Número total de goles", [("Más de 2", "over", 1.42), ("Menos de 2", "under", 2.85)])
    state.bet("1ª mitad - Número total de goles", [("Más de 0,5", "over", 1.36), ("Menos de 0,5", "under", 2.95)])
    state.bet("Número total de goles marcados por Atl. Madrid", [("Más de 1,5", "over", 1.92), ("Menos de 1,5", "under", 1.8)])
    state.bet("1ª mitad - Número Total de goles de Alavés", [("Más de 0,5", "over", 2.4), ("Menos de 0,5", "under", 1.5)])
    markets = state.markets()
    assert prices(markets["OU_2.5"]) == [("Over", 1.86), ("Under", 1.92)]
    assert "OU_2" in markets and "OU_HT_0.5" in markets
    assert prices(markets["OU_AWAY_1.5"]) == [("Over", 1.92), ("Under", 1.8)]
    assert prices(markets["OU_HOME_HT_0.5"]) == [("Over", 2.4), ("Under", 1.5)]


def test_asian_handicap_is_expressed_from_the_home_side_and_validated():
    state = main_state()
    state.bet("Hándicap asiático (handicap)", [("Alavés +1.5", "no", 1.3), ("Atl. Madrid -1.5", "yes", 3.45)])
    state.bet("Hándicap asiático (handicap)", [("Alavés -1.5", "yes", 8.5), ("Atl. Madrid +1.5", "no", 1.07)])
    state.bet("1ª mitad - Hándicap asiático (handicap)", [("Alavés 0", "1714", 2.5), ("Atl. Madrid 0", "1715", 1.48)])
    state.bet("Hándicap asiático (handicap)", [("Alavés +2.5", "no", 1.09), ("Atl. Madrid -1.0", "yes", 7.25)])  # líneas incoherentes
    markets = state.markets()
    assert prices(markets["AH_+1.5"]) == [("1", 1.3), ("2", 3.45)]
    assert prices(markets["AH_-1.5"]) == [("1", 8.5), ("2", 1.07)]
    assert "AH_HT_0" in markets
    assert not any(key.startswith("AH_+2.5") for key in markets)


def test_bets_with_an_unavailable_selection_are_dropped():
    state = main_state().bet("Ambos equipos marcan", [("Sí", "74", 1.76), ("No", "76", 2.05, False)])
    assert "BTTS" not in state.markets()


def test_unknown_titles_and_unknown_codes_are_ignored():
    state = main_state()
    state.bet("Suplente goleador", [("Sí", "74", 2.65), ("No", "76", 1.37)])
    state.bet("Ambos equipos marcan", [("Sí", "74", 1.76), ("Quizá", "99", 2.05)])
    assert set(state.markets()) == {"1X2"}


def test_team_totals_are_skipped_when_the_team_name_is_ambiguous():
    # "Inter" está dentro de "Inter Miami": no se puede saber de qué equipo es el mercado
    state = State(home="Inter Miami", away="Inter").bet("Resultado", [("Inter Miami", "1", 2.0), ("Empate", "x", 3.0), ("Inter", "2", 3.5)])
    state.bet("Número total de goles marcados por Inter Miami", [("Más de 1,5", "over", 1.9), ("Menos de 1,5", "under", 1.9)])
    assert not any(key.startswith("OU_") for key in state.markets())


def test_started_or_unavailable_matches_give_nothing():
    assert State(status="LIVE").bet("Resultado", [("A", "1", 2.0), ("Empate", "x", 3.0), ("B", "2", 3.0)]).markets() == {}


def _listing(*matches):
    return {"matches": {str(m["matchId"]): m for m in matches}}


def _match(match_id, hours=5, status="PREMATCH", title="A - B", home="A", away="B", sport=1):
    start = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {
        "matchId": match_id, "status": status, "available": True, "sportId": sport, "title": title,
        "competitor1Name": home, "competitor2Name": away, "matchStart": int(start.timestamp()),
    }


def test_select_keeps_prematch_matches_inside_the_horizon_sorted_and_capped():
    provider = WinamaxProvider(horizon_hours=24, max_matches=2)
    listing = _listing(
        _match(1, hours=10), _match(2, hours=3), _match(3, hours=5), _match(4, hours=100),
        _match(5, hours=2, status="LIVE"), _match(6, hours=4, sport=2),
        _match(7, hours=1, title="Barcelona (F) - Real Madrid (F)", home="Barcelona (F)", away="Real Madrid (F)"),
    )
    assert provider._select(listing) == [2, 3]  # 7 es femenino, 5 en juego, 6 otro deporte, 4 fuera de horizonte, 1 fuera del tope


def test_no_requested_competition_means_no_browser():
    assert WinamaxProvider().fetch_markets(["baloncesto_nba"]) == []
