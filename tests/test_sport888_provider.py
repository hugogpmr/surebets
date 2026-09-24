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
