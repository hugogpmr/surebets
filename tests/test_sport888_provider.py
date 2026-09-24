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
    return {
        "id": id_,
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
    markets = provider._parse_events(RAW_RESPONSE, "futbol")

    assert len(markets) == 1
    m = markets[0]
    assert m.event == "Getafe vs. Rayo Vallecano"
    assert m.market_type == "1X2"
    assert [(o.name, o.odds) for o in m.outcomes] == [("1", 2.6), ("X", 2.9), ("2", 2.8)]
    assert all(o.bookmaker == "888sport" for o in m.outcomes)
    assert m.start_time == datetime(2026, 10, 19, 19, 0, tzinfo=timezone.utc)


def test_skips_events_that_are_not_pending_or_are_inplay():
    live = event("e2", "A", "B", {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0"), "s3": selection("s3", "2", "3.5")}, inplay=True)
    finished = event("e3", "A", "B", {"s1": selection("s1", "1", "2.0"), "s2": selection("s2", "X", "3.0"), "s3": selection("s3", "2", "3.5")}, event_status="SETTLED")
    data = {"events": {"e2": live, "e3": finished}}
    assert Sport888Provider()._parse_events(data, "futbol") == []


def test_skips_incomplete_or_suspended_markets():
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
        assert Sport888Provider()._parse_events(data, "futbol") == []


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
    assert Sport888Provider()._parse_events(data, "futbol") == []


def test_other_sports_are_ignored_when_not_configured():
    provider = Sport888Provider()
    assert provider.tournaments.get("baloncesto") is None
