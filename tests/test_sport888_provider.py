from datetime import datetime, timezone

from providers.sport888 import Sport888Provider


def competitor(id_, name, is_home):
    return {"id": id_, "name": name, "is_home_team": is_home}


def selection(id_, sel_type, price, **extra):
    return {
        "id": id_,
        "type": sel_type,
        "decimal_price": price,
        "active": True,
        "betable": True,
        "tradable": True,
        **extra,
    }


def market(id_, name, selections, **extra):
    return {"id": id_, "name": name, "active": True, "betable": True, "selections": selections, **extra}


def event(id_, home, away, selections, **extra):
    slug = f"{home}-vs-{away}".lower().replace(" ", "-")
    return {
        "id": id_,
        "slug": slug,
        "event_status": "PENDING",
        "inplay": False,
        "start_time": "2026-10-19T19:00:00+00:00",
        "competitors": {"1": competitor(1, home, True), "2": competitor(2, away, False)},
        "markets": {"m1": market("m1", "Ganador del partido", selections)},
        **extra,
    }


# Forma real de la respuesta de getTournamentMatches, capturada en vivo el
# 2026-09-24 (LaLiga, https://www.888sport.es/futbol/espana/la-liga/).
RAW_RESPONSE = {
    "events": {
        "e1": event(
            "e1",
            "Getafe",
            "Rayo Vallecano",
            {
                "s1": selection("s1", "1", "2.600"),
                "s2": selection("s2", "X", "2.900"),
                "s3": selection("s3", "2", "2.800"),
            },
        )
    },
    "event_order": [],
}


def test_parses_1x2_from_the_real_response_shape():
    provider = Sport888Provider()
    events = provider._parse_events(RAW_RESPONSE, "futbol")

    assert len(events) == 1
    event_name, m, slug, event_id = events[0]
    assert event_name == "Getafe vs. Rayo Vallecano"
    assert m.market_type == "1X2"
    assert [(o.name, o.odds) for o in m.outcomes] == [("1", 2.6), ("X", 2.9), ("2", 2.8)]
    assert all(o.bookmaker == "888sport" for o in m.outcomes)
    assert m.start_time == datetime(2026, 10, 19, 19, 0, tzinfo=timezone.utc)
    assert slug == "getafe-vs-rayo-vallecano"
    assert event_id == "e1"


def test_skips_events_that_are_not_pending_or_are_inplay():
    live = event("e2", "A", "B", {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0"), "s3": selection("s3", "2", "3.5")}, inplay=True)
    finished = event("e3", "A", "B", {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0"), "s3": selection("s3", "2", "3.5")}, event_status="SETTLED")
    data = {"events": {"e2": live, "e3": finished}}
    assert Sport888Provider()._parse_events(data, "futbol") == []


def test_skips_incomplete_or_suspended_markets_but_keeps_the_event():
    cases = [
        # falta una selección
        {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0")},
        # selección no apostable
        {
            "s1": selection("s1", "1", "2.0"),
            "s2": selection("s2", "X", "3.0", betable=False),
            "s3": selection("s3", "2", "3.5"),
        },
        # cuota 1.00: no apostable
        {
            "s1": selection("s1", "1", "1.00"),
            "s2": selection("s2", "X", "3.0"),
            "s3": selection("s3", "2", "3.5"),
        },
    ]
    for selections in cases:
        data = {"events": {"e1": event("e1", "A", "B", selections)}}
        events = Sport888Provider()._parse_events(data, "futbol")
        assert len(events) == 1 and events[0][1] is None


def test_skips_events_without_the_main_market_or_two_competitors():
    no_market = event("e1", "A", "B", {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0"), "s3": selection("s3", "2", "3.5")})
    no_market["markets"] = {}
    outright = {
        "id": "e4",
        "event_status": "PENDING",
        "inplay": False,
        "start_time": None,
        "competitors": {"1": competitor(1, "Solo un competidor", True)},
        "markets": {},
    }
    data = {"events": {"e1": no_market, "e4": outright}}
    events = Sport888Provider()._parse_events(data, "futbol")
    assert len(events) == 1 and events[0][1] is None  # e4 (1 solo competidor) ni siquiera entra


def test_other_sports_are_ignored_when_not_configured():
    provider = Sport888Provider()
    assert provider.tournaments.get("baloncesto") is None


# --- mercados de la ficha del partido (getEventData) -----------------------------------------------

def sel_extra(market_name, sel_type, price, db_name=None, line=None, **extra):
    return {
        "market_name": market_name,
        "type": sel_type,
        "selection_db_name": db_name,
        "decimal_price": price,
        "special_odds_value": line,
        "active": True,
        "betable": True,
        "tradable": True,
        **extra,
    }


def test_parses_fixed_markets_double_chance_btts_dnb_and_odd_even():
    provider = Sport888Provider()
    selections_by_id = {
        "6": [
            sel_extra("Double Chance", "1/X", "1.005"),
            sel_extra("Double Chance", "2/X", "10.000"),
            sel_extra("Double Chance", "1/2", "1.030"),
        ],
        "8": [sel_extra("Both Teams to Score", "Yes", "2.200"), sel_extra("Both Teams to Score", "No", "1.650")],
        "9": [sel_extra("Draw No Bet", "1", "1.010"), sel_extra("Draw No Bet", "2", "29.000")],
        "1323245": [
            sel_extra("Odd or Even Total", None, "1.800", db_name="Odd"),
            sel_extra("Odd or Even Total", None, "1.909", db_name="Even"),
        ],
    }
    data = {"event": {"markets": {"markets_selections": selections_by_id}}}
    markets = {m.market_type: m for m in provider._parse_event_extras(data, "A vs. B", "futbol")}

    assert [(o.name, o.odds) for o in markets["DC"].outcomes] == [("1X", 1.005), ("X2", 10.0), ("12", 1.03)]
    assert [(o.name, o.odds) for o in markets["BTTS"].outcomes] == [("Yes", 2.2), ("No", 1.65)]
    assert [(o.name, o.odds) for o in markets["DNB"].outcomes] == [("1", 1.01), ("2", 29.0)]
    assert [(o.name, o.odds) for o in markets["OE"].outcomes] == [("Odd", 1.8), ("Even", 1.909)]
    assert all(m.event == "A vs. B" and m.sport == "futbol" for m in markets.values())
    assert all(o.bookmaker == "888sport" for m in markets.values() for o in m.outcomes)


def test_parses_grouped_over_under_lines():
    provider = Sport888Provider()
    selections_by_id = {
        "1323275": {
            "0": {
                "0": sel_extra("Total Goals Over/Under", "Over", "1.200", line="2.5"),
                "2": sel_extra("Total Goals Over/Under", "Under", "4.500", line="2.5"),
            },
            "1": {
                "0": sel_extra("Total Goals Over/Under", "Over", "1.571", line="3.5"),
                "2": sel_extra("Total Goals Over/Under", "Under", "2.400", line="3.5"),
            },
            "grouped": True,
        }
    }
    data = {"event": {"markets": {"markets_selections": selections_by_id}}}
    markets = {m.market_type: m for m in provider._parse_event_extras(data, "A vs. B", "futbol")}

    assert [(o.name, o.odds) for o in markets["OU_2.5"].outcomes] == [("Over", 1.2), ("Under", 4.5)]
    assert [(o.name, o.odds) for o in markets["OU_3.5"].outcomes] == [("Over", 1.571), ("Under", 2.4)]


def test_incomplete_over_under_line_is_dropped():
    provider = Sport888Provider()
    selections_by_id = {
        "1323275": {
            "0": {"0": sel_extra("Total Goals Over/Under", "Over", "1.200", line="2.5")},  # sin Under
            "grouped": True,
        }
    }
    data = {"event": {"markets": {"markets_selections": selections_by_id}}}
    assert provider._parse_event_extras(data, "A vs. B", "futbol") == []


def test_parses_two_way_handicap_but_not_three_way():
    provider = Sport888Provider()
    selections_by_id = {
        "1619557": [
            sel_extra("Handicap 2-Way", "1", "1.615", line="-2.5"),
            sel_extra("Handicap 2-Way", "2", "2.250", line="2.5"),
        ],
        # hándicap de 3 vías (con empate): no tiene pareja en otra fuente, se descarta.
        "14": [
            sel_extra("Handicap", "1", "1.005", line="1.0"),
            sel_extra("Handicap", "X", "36.000", line="1.0"),
            sel_extra("Handicap", "2", "101.000", line="-1.0"),
        ],
    }
    data = {"event": {"markets": {"markets_selections": selections_by_id}}}
    markets = {m.market_type: m for m in provider._parse_event_extras(data, "A vs. B", "futbol")}

    assert list(markets.keys()) == ["AH_-2.5"]
    assert [(o.name, o.odds) for o in markets["AH_-2.5"].outcomes] == [("1", 1.615), ("2", 2.25)]


def test_handicap_with_inconsistent_lines_is_dropped():
    provider = Sport888Provider()
    selections_by_id = {
        "1619557": [
            sel_extra("Handicap 2-Way", "1", "1.615", line="-2.5"),
            sel_extra("Handicap 2-Way", "2", "2.250", line="3.5"),  # no es -(-2.5)
        ],
    }
    data = {"event": {"markets": {"markets_selections": selections_by_id}}}
    assert provider._parse_event_extras(data, "A vs. B", "futbol") == []


def test_flatten_selections_handles_both_shapes():
    flat_list = [sel_extra("Both Teams to Score", "Yes", "2.0")]
    assert Sport888Provider._flatten_selections(flat_list) == flat_list

    grouped = {"0": {"0": sel_extra("X", "Over", "1.5", line="2.5")}, "grouped": True}
    assert Sport888Provider._flatten_selections(grouped) == [sel_extra("X", "Over", "1.5", line="2.5")]

    assert Sport888Provider._flatten_selections(None) == []


# --- todas las ligas + baloncesto y tenis (2026-09-29) ---------------------------------------------

from datetime import timedelta  # noqa: E402


def ev_data(*markets):
    """Respuesta de getEventData con los mercados dados (cada uno, su `markets_selections`)."""
    return {"event": {"markets": {"markets_selections": {f"m{i}": raw for i, raw in enumerate(markets)}}}}


def basket_sel(market_name, sel_type, price, db_name=None, line="", **extra):
    return sel_extra(market_name, sel_type, price, db_name=db_name, line=line, **extra)


def test_flatten_selections_handles_a_list_of_line_groups():
    # forma real del "Point Spread": lista de {"<línea>": [selecciones]}
    a = basket_sel("Point Spread", "1", "1.9", "Home  (+1.5)", "+1.5")
    b = basket_sel("Point Spread", "2", "1.8", "Away  (-1.5)", "-1.5")
    raw = [{"-1.5": [b, a]}, {"-2.5": [b]}]
    assert Sport888Provider._flatten_selections(raw) == [b, a, b]


BASKETBALL_DATA = ev_data(
    [basket_sel("Money Line", "2", "1.615", "Minnesota Lynx"), basket_sel("Money Line", "1", "2.3", "New York Liberty")],
    [{"-1.5": [basket_sel("Point Spread", "2", "1.667", "Minnesota Lynx  (-1.5)", "-1.5"),
               basket_sel("Point Spread", "1", "2.1", "New York Liberty  (+1.5)", "+1.5")]},
     {"-2.5": [basket_sel("Point Spread", "2", "2.0", "Minnesota Lynx  (-2.5)", "-2.5"),
               basket_sel("Point Spread", "1", "1.8", "New York Liberty  (+2.5)", "+2.5")]}],
    {"0": {"0": basket_sel("Total Points", "Over", "1.667", "Over (170.5)", "170.5"),
           "1": basket_sel("Total Points", "Under", "2.1", "Under (170.5)", "170.5")}, "grouped": True},
    [basket_sel("Odd or Even Total Points", None, "1.85", "Odd"), basket_sel("Odd or Even Total Points", None, "1.85", "Even")],
    [basket_sel("Will There Be Overtime?", "Yes", "10.0", "Yes"), basket_sel("Will There Be Overtime?", "No", "1.04", "No")],
    [basket_sel("1st Half Draw No Bet", "2", "1.667", "Minnesota Lynx"), basket_sel("1st Half Draw No Bet", "1", "2.1", "New York Liberty")],
    {"0": {"0": basket_sel("1st Quarter Total Points", "Over", "1.9", "Over (45.5)", "45.5"),
           "1": basket_sel("1st Quarter Total Points", "Under", "1.8", "Under (45.5)", "45.5")}, "grouped": True},
    # el ganador a dos vías de una mitad NO se emite: se ignora
    [basket_sel("1st Half Money Line", "1", "1.667", "A"), basket_sel("1st Half Money Line", "2", "2.05", "B")],
)


def test_basketball_extras_use_the_same_prefixes_as_altenar_kambi_and_bet777():
    markets = {m.market_type: m for m in Sport888Provider()._parse_event_extras(BASKETBALL_DATA, "A vs. B", "baloncesto")}
    assert {o.name: o.odds for o in markets["ML"].outcomes} == {"1": 2.3, "2": 1.615}
    assert {o.name: o.odds for o in markets["AH_+1.5"].outcomes} == {"1": 2.1, "2": 1.667}
    assert {o.name: o.odds for o in markets["AH_+2.5"].outcomes} == {"1": 1.8, "2": 2.0}
    assert {o.name: o.odds for o in markets["OU_170.5"].outcomes} == {"Over": 1.667, "Under": 2.1}
    assert {o.name: o.odds for o in markets["OE"].outcomes} == {"Odd": 1.85, "Even": 1.85}
    assert {o.name: o.odds for o in markets["OT"].outcomes} == {"Yes": 10.0, "No": 1.04}
    assert {o.name: o.odds for o in markets["DNB_HT"].outcomes} == {"1": 2.1, "2": 1.667}
    assert "OU_Q1_45.5" in markets
    assert not any("HT" in t and t.startswith("ML") for t in markets)


TENNIS_DATA = ev_data(
    [basket_sel("Which player will win the match?", "1", "1.727", "Player A"), basket_sel("Which player will win the match?", "2", "2.0", "Player B")],
    [basket_sel("Set Winner (Set 1)", "1", "1.727", "Player A"), basket_sel("Set Winner (Set 1)", "2", "2.0", "Player B")],
    [basket_sel("Set Winner (Set 2)", "1", "1.8", "Player A"), basket_sel("Set Winner (Set 2)", "2", "1.909", "Player B")],
    {"0": {"0": basket_sel("Total", "Over", "1.571", "Over (19.5)", "19.5"),
           "1": basket_sel("Total", "Under", "2.3", "Under (19.5)", "19.5")}, "grouped": True},
    # hándicap de tenis: sin `type`, el lado sale del nombre ("1  (+0.5)")
    [{"+0.5": [basket_sel("Game Handicap", None, "1.7", "1  (+0.5)", "+0.5"), basket_sel("Game Handicap", None, "2.05", "2  (-0.5)", "-0.5")]}],
    [basket_sel("Set Betting", None, "3.25", "2 2:0")],  # se ignora
)


def test_tennis_extras_read_the_handicap_side_from_the_name():
    markets = {m.market_type: m for m in Sport888Provider()._parse_event_extras(TENNIS_DATA, "A vs. B", "tenis")}
    assert set(markets) == {"ML", "ML_SET1", "ML_SET2", "OU_19.5", "AH_+0.5"}
    assert {o.name: o.odds for o in markets["AH_+0.5"].outcomes} == {"1": 1.7, "2": 2.05}


def upcoming_event(id_, name_home, name_away, hours, **extra):
    start = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {
        "id": id_,
        "event_status": "PENDING",
        "inplay": False,
        "start_time": start.isoformat(),
        "sport_slug": "basketball",
        "category_slug": "europe",
        "tournament_slug": "uleb-eurocup",
        "slug": f"e{id_}",
        "tournament_name": "ULEB Eurocup",
        "category_name": "Europa",
        "competitors": {"1": competitor(1, name_home, True), "2": competitor(2, name_away, False)},
        "markets": {},
        **extra,
    }


def test_upcoming_events_are_filtered_by_state_horizon_virtual_and_women_and_get_their_own_url():
    data = {
        "events": {
            "ok": upcoming_event(1, "A", "B", 5),
            "late": upcoming_event(2, "C", "D", 80),  # fuera del horizonte
            "past": upcoming_event(3, "E", "F", -1),
            "live": upcoming_event(4, "G", "H", 5, inplay=True),
            "virtual": upcoming_event(5, "I", "J", 5, tournament_name="eFootball Battle"),
            "women": upcoming_event(6, "K", "L", 5, tournament_name="UEFA Champions League femenina"),
            "noslug": upcoming_event(7, "M", "N", 5, tournament_slug=None),
        }
    }
    football = Sport888Provider()._parse_upcoming(data, "futbol")
    assert [e["name"] for e in football] == ["A vs. B"]
    assert football[0]["url"].endswith("/basketball/europe/uleb-eurocup/e1/1")
    # el filtro de femenino solo aplica al fútbol
    basketball = Sport888Provider()._parse_upcoming(data, "baloncesto")
    assert sorted(e["name"] for e in basketball) == ["A vs. B", "K vs. L"]


def test_discovery_is_the_default_and_explicit_tournaments_keep_the_old_mode():
    assert Sport888Provider().discover is True
    assert Sport888Provider(tournaments={"futbol": []}).discover is False
