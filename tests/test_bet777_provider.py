from datetime import datetime, timedelta, timezone

from providers.bet777 import Bet777Provider, _fmt_line, parse_event_markets


def out(kind, name, odds, **extra):
    return {
        "kind": kind,
        "name": name,
        "odds": odds,
        "display_odds": {"decimal": f"{odds:.2f}"},
        "suspended": False,
        "visible": True,
        "status": True,
        **extra,
    }


def mk(name, outcomes, **extra):
    return {"name_untranslated": name, "is_suspended": False, "can_cashout": True, "outcomes": outcomes, **extra}


def by_type(markets):
    return {m.market_type: m for m in markets}


def odds(market):
    return {o.name: o.odds for o in market.outcomes}


DETAILS = {
    "markets": [
        mk("Match Result", [out("W1", "Home", 2.9), out("X", "Draw", 3.34), out("W2", "Away", 2.43)]),
        mk("Match Result (Early Payout)", [out("W1", "Home", 2.9), out("X", "Draw", 3.34), out("W2", "Away", 2.43)]),
        mk("Double Chance", [out("1X", "1X", 1.5), out("12", "12", 1.3), out("X2", "X2", 1.4)]),
        mk("Draw No Bet", [out("Team1", "Home", 2.1), out("Team2", "Away", 1.7)]),
        mk("Both Teams To Score", [out("Yes", "Yes", 1.7), out("No", "No", 1.93)]),
        mk("Total Goals Odd/Even", [out("Even", "Even", 1.9), out("Odd", "Odd", 1.9)]),
        mk(
            "Total Goals",
            [
                out("Over", "Over (1.5)", 1.3), out("Under", "Under (1.5)", 2.98),
                out("Over", "Over (2)", 1.48), out("Under", "Under (2)", 2.32),
                out("Over", "Over (2.5)", 1.9), out("Under", "Under (2.5)", 1.9),
                # línea sin su pareja: no se emite
                out("Over", "Over (3.5)", 3.1),
            ],
        ),
        mk("Total Goals Asian", [out("Over", "Over (2.25)", 1.7), out("Under", "Under (2.25)", 2.0)]),
        mk("Team 1 Total Goals", [out("Over", "Over (0.5)", 1.5), out("Under", "Under (0.5)", 2.5)]),
        mk("Team 2 Total Goals", [out("Over", "Over (0.5)", 1.6), out("Under", "Under (0.5)", 2.3)]),
        mk(
            "Goals Handicap",
            [out("Home", "Home (-1.5)", 5.1), out("Away", "Away (1.5)", 1.13), out("Home", "Home (0)", 2.6), out("Away", "Away (0)", 1.45)],
        ),
        mk("Goals Asian Handicap", [out("Home", "Home (-0.75)", 2.98), out("Away", "Away (0.75)", 1.3)]),
        mk("1st Half Result", [out("W1", "Home", 3.5), out("X", "Draw", 2.1), out("W2", "Away", 3.6)]),
        mk("2nd Half Result", [out("W1", "Home", 3.2), out("X", "Draw", 2.5), out("W2", "Away", 3.0)]),
        mk("1st Half Both Teams To Score", [out("Yes", "Yes", 3.2), out("No", "No", 1.3)]),
        mk("1st Half Total Goals Asian", [out("Over", "Over (0.75)", 1.5), out("Under", "Under (0.75)", 2.28)]),
        mk("2nd Half Goals Handicap", [out("Home", "Home (-0.5)", 3.0), out("Away", "Away (0.5)", 1.35)]),
        mk("1st Half Team 1 Total Goals", [out("Over", "Over (0.5)", 2.2), out("Under", "Under (0.5)", 1.6)]),
        # no se emiten
        mk("Correct Score", [out("Home-Away", "0-0", 9.0), out("Home-Away", "1-0", 7.0)]),
        mk("Goals Handicap 3 Way", [out("Home", "Home (-2)", 8.0), out("Tie", "Tie: Away (2)", 5.0), out("Away", "Away (2)", 1.1)]),
        mk("1st Half Or Match Result", [out("W1", "Home", 2.0), out("X", "X", 3.0), out("W2", "Away", 4.0)]),
    ]
}


def test_full_time_fixed_markets_use_the_shared_naming():
    markets = by_type(parse_event_markets(DETAILS, "Malaga CF vs. Espanyol"))
    assert odds(markets["1X2"]) == {"1": 2.9, "X": 3.34, "2": 2.43}
    assert odds(markets["DNB"]) == {"1": 2.1, "2": 1.7}
    assert odds(markets["BTTS"]) == {"Yes": 1.7, "No": 1.93}
    assert odds(markets["OE"]) == {"Odd": 1.9, "Even": 1.9}
    assert all(o.bookmaker == "bet777" for m in markets.values() for o in m.outcomes)


def test_totals_are_split_per_line_and_only_complete_pairs_are_emitted():
    markets = by_type(parse_event_markets(DETAILS, "A vs. B"))
    assert odds(markets["OU_1.5"]) == {"Over": 1.3, "Under": 2.98}
    assert odds(markets["OU_2"]) == {"Over": 1.48, "Under": 2.32}  # línea entera
    assert odds(markets["OU_2.5"]) == {"Over": 1.9, "Under": 1.9}
    assert "OU_3.5" not in markets  # sin su lado Under
    assert odds(markets["OU_2/2.5"]) == {"Over": 1.7, "Under": 2.0}  # línea de cuarto, como Altenar/Kambi
    assert odds(markets["OU_HOME_0.5"]) == {"Over": 1.5, "Under": 2.5}
    assert odds(markets["OU_AWAY_0.5"]) == {"Over": 1.6, "Under": 2.3}


def test_handicap_lines_are_expressed_from_the_home_team_with_sign():
    markets = by_type(parse_event_markets(DETAILS, "A vs. B"))
    assert odds(markets["AH_-1.5"]) == {"1": 5.1, "2": 1.13}
    assert odds(markets["AH_0"]) == {"1": 2.6, "2": 1.45}
    assert odds(markets["AH_-0.5/-1"]) == {"1": 2.98, "2": 1.3}  # -0.75, la línea más cercana a cero primero


def test_half_time_and_second_half_variants():
    markets = by_type(parse_event_markets(DETAILS, "A vs. B"))
    assert odds(markets["1X2_HT"]) == {"1": 3.5, "X": 2.1, "2": 3.6}
    assert odds(markets["1X2_2H"]) == {"1": 3.2, "X": 2.5, "2": 3.0}
    assert odds(markets["BTTS_HT"]) == {"Yes": 3.2, "No": 1.3}
    assert odds(markets["OU_HT_0.5/1"]) == {"Over": 1.5, "Under": 2.28}
    assert odds(markets["AH_2H_-0.5"]) == {"1": 3.0, "2": 1.35}
    assert odds(markets["OU_HOME_HT_0.5"]) == {"Over": 2.2, "Under": 1.6}


def test_markets_that_are_not_exhaustive_or_are_duplicates_are_left_out():
    types = {m.market_type for m in parse_event_markets(DETAILS, "A vs. B")}
    assert not any(t.startswith(("CS", "DC", "EH")) for t in types)
    assert len([t for t in types if t == "1X2"]) == 1  # "Early Payout" no duplica el 1X2


def test_suspended_outcomes_and_markets_are_never_emitted():
    details = {
        "markets": [
            mk("Match Result", [out("W1", "Home", 2.0), out("X", "Draw", 3.0, suspended=True), out("W2", "Away", 4.0)]),
            mk("Both Teams To Score", [out("Yes", "Yes", 1.7), out("No", "No", 1.9)], is_suspended=True),
            mk("Total Goals", [out("Over", "Over (2.5)", 1.9, visible=False), out("Under", "Under (2.5)", 1.9)]),
            mk("Draw No Bet", [out("Team1", "Home", 1.0), out("Team2", "Away", 2.0)]),  # cuota 1.00: no apostable
        ]
    }
    assert parse_event_markets(details, "A vs. B") == []


def test_markets_serialised_as_an_object_with_numeric_keys_are_read():
    # visto en vivo: algunos partidos devuelven "markets" como {"0": {...}, "1": {...}}
    details = {"markets": {"0": DETAILS["markets"][0], "1": DETAILS["markets"][4]}}
    assert {m.market_type for m in parse_event_markets(details, "A vs. B")} == {"1X2", "BTTS"}


def test_cash_out_flag_comes_from_the_market():
    details = {"markets": [mk("Both Teams To Score", [out("Yes", "Yes", 1.7), out("No", "No", 1.9)], can_cashout=False)]}
    (market,) = parse_event_markets(details, "A vs. B")
    assert [o.cash_out for o in market.outcomes] == [False, False]


def test_line_formatting_matches_altenar_and_kambi():
    assert _fmt_line(2.25) == "2/2.5" and _fmt_line(-0.75, signed=True) == "-0.5/-1"
    assert _fmt_line(1.5, signed=True) == "+1.5" and _fmt_line(0, signed=True) == "0" and _fmt_line(2) == "2"


# --- listado de partidos y ciclo completo --------------------------------------------------------


def event(idx, home, away, start, **extra):
    return {
        "id": f"1-{idx}",
        "teams": [home, away],
        "starts_at": start.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
        "is_live": False,
        "is_suspended": False,
        **extra,
    }


def listing(events_by_competition):
    return {
        "tree": [
            {"name": "Football", "competitions": [{"name": name, "events": evs} for name, evs in events_by_competition.items()]}
        ]
    }


class FakeBet777(Bet777Provider):
    def __init__(self, listing_payload, details_by_id, **kwargs):
        super().__init__(**kwargs)
        self._listing = listing_payload
        self._details = details_by_id
        self.detail_calls = []

    def _get_json(self, client, endpoint, **params):
        if endpoint == "events":
            return self._listing
        self.detail_calls.append(params["event_id"])
        return self._details[params["event_id"]]


def test_events_are_filtered_by_state_horizon_virtual_and_women():
    now = datetime.now(timezone.utc)
    soon, far = now + timedelta(hours=5), now + timedelta(days=9)
    payload = listing(
        {
            "La Liga": [
                event(1, "Malaga CF", "Espanyol", soon),
                event(2, "Live A", "Live B", soon, is_live=True),
                event(3, "Susp A", "Susp B", soon, is_suspended=True),
                event(4, "Far A", "Far B", far),
                event(5, "Started A", "Started B", now - timedelta(minutes=5)),
            ],
            "UEFA Champions League - Women": [event(6, "Bayern (Wom)", "City (Wom)", soon)],
            "Esports Battle": [event(7, "Celta (Voron)", "Betis (Kuzma)", soon)],
        }
    )
    provider = FakeBet777(payload, {"1-1": DETAILS}, horizon_hours=48)
    markets = provider.fetch_markets(["futbol"])
    assert provider.detail_calls == ["1-1"]  # solo el partido pre-partido, cercano y no femenino/virtual
    assert {m.event for m in markets} == {"Malaga CF vs. Espanyol"}
    assert all(m.start_time == datetime.fromisoformat(soon.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00") for m in markets)
    assert provider.fast_recheck is True and provider.name == "bet777"


def test_women_can_be_kept_when_asked():
    now = datetime.now(timezone.utc)
    payload = listing({"UEFA Champions League - Women": [event(1, "Bayern (Wom)", "City (Wom)", now + timedelta(hours=3))]})
    provider = FakeBet777(payload, {"1-1": DETAILS}, exclude_women=False)
    assert provider.fetch_markets(["futbol"])


def test_non_football_requests_do_nothing_and_a_broken_event_does_not_stop_the_others():
    provider = FakeBet777(listing({}), {})
    assert provider.fetch_markets(["baloncesto_nba"]) == []

    now = datetime.now(timezone.utc)
    payload = listing({"La Liga": [event(1, "A", "B", now + timedelta(hours=2)), event(2, "C", "D", now + timedelta(hours=2))]})
    good = {"markets": [DETAILS["markets"][0]]}
    broken = {"markets": [42, "raro"]}  # elementos que no son mercados
    provider = FakeBet777(payload, {"1-1": broken, "1-2": good})
    markets = provider.fetch_markets(["futbol"])
    assert {m.event for m in markets} == {"C vs. D"}


def test_get_json_retries_rate_limits(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)

    class Response:
        def __init__(self, status, payload=None):
            self.status_code, self._payload = status, payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self._payload

    class Client:
        def __init__(self, responses):
            self.responses, self.params = list(responses), []

        def get(self, url, params=None):
            self.params.append(params)
            return self.responses.pop(0)

    client = Client([Response(429), Response(503), Response(200, {"tree": []})])
    assert Bet777Provider()._get_json(client, "events", sport="football") == {"tree": []}
    assert all(p["bookmaker"] == "bet777es" for p in client.params) and len(client.params) == 3
