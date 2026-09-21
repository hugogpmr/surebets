from datetime import datetime, timedelta, timezone

from providers.kambi import KambiProvider, parse_event_offers

HOME, AWAY = "Valencia", "Real Sociedad"


def _outcome(kind, odds, line=None, participant=None, status="OPEN"):
    return {"type": kind, "odds": odds, "line": line, "participant": participant, "status": status}


def _offer(label, offer_type, outcomes):
    return {"criterion": {"englishLabel": label}, "betOfferType": {"englishName": offer_type}, "outcomes": outcomes}


def _three_way(label, one=2800, cross=3250, two=2550, offer_type="Match"):
    return _offer(
        label,
        offer_type,
        [_outcome("OT_ONE", one, participant=HOME), _outcome("OT_CROSS", cross), _outcome("OT_TWO", two, participant=AWAY)],
    )


def _over_under(label, line, over, under, offer_type="Over/Under"):
    return _offer(label, offer_type, [_outcome("OT_OVER", over, line), _outcome("OT_UNDER", under, line)])


DETAILS = {
    "betOffers": [
        _three_way("Full Time"),
        _three_way("Half Time", 3250, 2170, 3050),
        _three_way("2nd Half", 2950, 2550, 2750),
        _three_way("Most Corners", 1850, 7000, 2200),
        _three_way("Most Corners - 1st Half", 1980, 4400, 2250),
        _three_way("Full Time - 2UP", 2600, 3200, 2400),
        _offer("Draw No Bet", "Match", [_outcome("OT_ONE", 1910), _outcome("OT_TWO", 1750)]),
        _offer("Both Teams To Score", "Yes/No", [_outcome("OT_YES", 1660), _outcome("OT_NO", 2100)]),
        _offer("Both Teams To Score - 1st Half", "Yes/No", [_outcome("OT_YES", 4100), _outcome("OT_NO", 1160)]),
        # oferta con un resultado suspendido: no es un mercado completo
        _offer("Penalty Kick awarded", "Yes/No", [_outcome("OT_YES", 3100), _outcome("OT_NO", None, status="SUSPENDED")]),
        _over_under("Total Goals", 2500, 1910, 1870),
        _over_under("Total Goals - 1st Half", 500, 1370, 2850),
        _over_under("Total Corners", 9500, 2000, 1710),
        _over_under("Total Corners By Real Sociedad - 1st Half", 1500, 1610, 2020),
        _over_under("Total Cards - Valencia", 2500, 2380, 1500),
        _over_under("Total Cards - Otro Equipo", 2500, 2380, 1500),
        # "Total asiático" repite la línea 2.5 (ya cubierta) y añade una de cuarto
        _over_under("Asian Total", 2500, 1900, 1880, "Asian Over/Under"),
        _over_under("Asian Total", 2250, 1700, 2100, "Asian Over/Under"),
        _offer(
            "Asian Handicap",
            "Asian Handicap",
            [_outcome("OT_UNTYPED", 2700, -500, HOME), _outcome("OT_UNTYPED", 1450, 500, AWAY)],
        ),
        _offer(
            "Asian Handicap - 1st Half",
            "Asian Handicap",
            [_outcome("OT_UNTYPED", 2550, -250, HOME), _outcome("OT_UNTYPED", 1460, 250, AWAY)],
        ),
        # las dos "líneas" no describen el mismo hándicap: se descarta
        _offer(
            "Asian Handicap",
            "Asian Handicap",
            [_outcome("OT_UNTYPED", 2000, -500, HOME), _outcome("OT_UNTYPED", 1800, 1000, AWAY)],
        ),
        # tipos que no se emiten (solapados, de jugador...)
        _offer("Double Chance", "Double Chance", [_outcome("OT_ONE_OR_CROSS", 1500)]),
        _offer("To Score", "Player Occurrence Line", [_outcome("OT_YES", 12000, 1000, "José Gayà")]),
    ]
}


def _parse(bookmaker="paf"):
    markets = parse_event_offers(DETAILS, "Valencia vs. Real Sociedad", "futbol", bookmaker, HOME, AWAY)
    return {m.market_type: m for m in markets}, markets


def _prices(market):
    return [(o.name, o.odds) for o in market.outcomes]


def test_three_way_markets_use_the_same_names_as_other_providers():
    types, _ = _parse()

    assert _prices(types["1X2"]) == [("1", 2.8), ("X", 3.25), ("2", 2.55)]
    assert _prices(types["1X2_HT"]) == [("1", 3.25), ("X", 2.17), ("2", 3.05)]
    assert "1X2_2H" in types
    assert _prices(types["CORNERS_1X2"]) == [("1", 1.85), ("X", 7.0), ("2", 2.2)]
    assert "CORNERS_1X2_HT" in types


def test_unsupported_and_overlapping_markets_are_not_emitted():
    types, _ = _parse()

    assert not any(key.startswith(("DC", "TO_")) for key in types)
    assert "PENALTY" not in types  # tenía un resultado suspendido
    # "Full Time - 2UP" no debe pisar el 1X2 normal
    assert types["1X2"].outcomes[0].odds == 2.8


def test_draw_no_bet_and_both_teams_to_score():
    types, _ = _parse()

    assert _prices(types["DNB"]) == [("1", 1.91), ("2", 1.75)]
    assert _prices(types["BTTS"]) == [("Yes", 1.66), ("No", 2.1)]
    assert _prices(types["BTTS_HT"]) == [("Yes", 4.1), ("No", 1.16)]


def test_over_under_lines_periods_and_team_totals():
    types, _ = _parse()

    assert _prices(types["OU_2.5"]) == [("Over", 1.91), ("Under", 1.87)]
    assert _prices(types["OU_HT_0.5"]) == [("Over", 1.37), ("Under", 2.85)]
    assert "CORNERS_OU_9.5" in types
    assert _prices(types["CORNERS_OU_AWAY_HT_1.5"]) == [("Over", 1.61), ("Under", 2.02)]


def test_asian_total_only_adds_lines_not_already_offered_by_total():
    types, markets = _parse()

    assert sum(1 for m in markets if m.market_type == "OU_2.5") == 1
    assert _prices(types["OU_2.5"]) == [("Over", 1.91), ("Under", 1.87)]  # gana el "Total" normal
    assert "OU_2/2.5" in types  # línea de cuarto, solo en "Total asiático"


def test_team_totals_require_a_known_team_name():
    types, _ = _parse()

    assert _prices(types["CARDS_OU_HOME_2.5"]) == [("Over", 2.38), ("Under", 1.5)]
    # "Otro Equipo" no es ni el local ni el visitante: no genera mercado
    assert [k for k in types if k.startswith("CARDS_OU")] == ["CARDS_OU_HOME_2.5"]


def test_asian_handicap_is_expressed_from_the_home_side_and_validates_both_lines():
    types, markets = _parse()

    assert _prices(types["AH_-0.5"]) == [("1", 2.7), ("2", 1.45)]
    # línea de cuarto de la 1ª parte: -0.25 -> "0/-0.5" (la más cercana a cero primero)
    assert _prices(types["AH_HT_0/-0.5"]) == [("1", 2.55), ("2", 1.46)]
    # el hándicap con líneas incoherentes (-0.5 / +1) no se emite: solo hay un AH_-0.5
    assert sum(1 for m in markets if m.market_type == "AH_-0.5") == 1


class _FakeProvider(KambiProvider):
    def __init__(self, listings, details):
        super().__init__(operators={"op_a": "casa_a", "op_b": "casa_b"}, horizon_hours=48)
        self._listings = listings
        self._details = details

    def _get_json(self, client, operator, path, **params):
        if path.startswith("listView"):
            return {"events": [{"event": e} for e in self._listings[operator]]}
        return self._details


def _event(event_id, home, away, hours_ahead=5, state="NOT_STARTED"):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": event_id, "homeName": home, "awayName": away, "start": start, "state": state}


def test_only_events_listed_by_both_houses_are_fetched_and_named_once():
    provider = _FakeProvider(
        listings={
            "op_a": [_event(1, HOME, AWAY), _event(2, "Solo", "A")],
            "op_b": [_event(1, HOME, AWAY)],
        },
        details=DETAILS,
    )

    markets = provider._fetch_football(client=None)

    assert {m.event for m in markets} == {"Valencia vs. Real Sociedad"}
    assert {o.bookmaker for m in markets for o in m.outcomes} == {"casa_a", "casa_b"}


def test_live_or_out_of_horizon_events_are_ignored():
    provider = _FakeProvider(
        listings={
            "op_a": [_event(1, "A", "B", state="STARTED"), _event(2, "C", "D", hours_ahead=200)],
            "op_b": [_event(1, "A", "B", state="STARTED"), _event(2, "C", "D", hours_ahead=200)],
        },
        details=DETAILS,
    )

    assert provider._fetch_football(client=None) == []


def test_returns_nothing_when_no_football_sport_requested():
    assert KambiProvider().fetch_markets(["tenis_atp"]) == []


def test_get_json_retries_transient_connection_errors_and_rate_limits(monkeypatch):
    import httpx

    import providers.kambi as kambi_module

    monkeypatch.setattr(kambi_module.time, "sleep", lambda _s: None)
    calls = []

    class _Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class _Client:
        def get(self, url, params):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.ConnectError("SSL EOF")
            if len(calls) == 2:
                return _Response(429)
            return _Response(200)

    assert KambiProvider()._get_json(_Client(), "pafes", "x.json") == {"ok": True}
    assert len(calls) == 3


def test_cash_out_and_odds_change_time_are_read_from_offer_and_outcome():
    def outcome(kind, odds, cash_out, changed, participant=None):
        raw = _outcome(kind, odds, participant=participant)
        raw.update(cashOutStatus=cash_out, changedDate=changed)
        return raw

    offer = _offer(
        "Full Time",
        "Match",
        [
            outcome("OT_ONE", 2800, "ENABLED", "2026-09-20T21:16:57Z", HOME),
            outcome("OT_CROSS", 3250, "DISABLED", "2026-09-20T21:20:00Z"),  # la oferta lo tiene, la selección no
            outcome("OT_TWO", 2550, "ENABLED", None, AWAY),
        ],
    )
    offer["cashOutStatus"] = "ENABLED"
    [market] = parse_event_offers({"betOffers": [offer]}, "Valencia vs. Real Sociedad", "futbol", "paf", HOME, AWAY)

    one, cross, two = market.outcomes
    assert one.cash_out is True
    assert one.odds_changed_at == datetime(2026, 9, 20, 21, 16, 57, tzinfo=timezone.utc)
    assert cross.cash_out is False
    assert two.odds_changed_at is None


def test_cash_out_is_unknown_when_the_source_does_not_say():
    types, _ = _parse()  # las ofertas de prueba no traen cashOutStatus

    assert all(o.cash_out is None and o.odds_changed_at is None for m in types.values() for o in m.outcomes)


def _kambi_event_with_path(event_id, home, away, *path_names):
    event = _event(event_id, home, away)
    event["path"] = [{"name": n, "englishName": n} for n in path_names]
    return event


def test_esports_and_womens_football_are_excluded_by_default_and_can_be_re_enabled():
    events = [
        _kambi_event_with_path(1, "Valencia", "Sevilla", "Football", "Spain", "La Liga"),
        _kambi_event_with_path(2, "Celta Vigo (Voron)", "Levante (k0tik)", "Football", "|Esports Football|", "Cyber Live Arena (2x5 min)"),
        _kambi_event_with_path(3, "Chivas", "Tigres", "Football", "Mexico", "Liga MX Femenil (W)"),
        _kambi_event_with_path(4, "FC Porto (W)", "S.C. Braga (F)", "Football", "Portugal", "Campeonato Nacional"),
    ]

    def listed(**kwargs):
        provider = KambiProvider(operators={"op": "casa"}, **kwargs)
        provider._get_json = lambda client, operator, path, **params: {"events": [{"event": e} for e in events]}
        return set(provider._list_events(None, "op"))

    assert listed() == {1}
    assert listed(exclude_women=False) == {1, 3, 4}
    assert listed(exclude_esports=False) == {1, 2}


def test_double_chance_full_time_and_halves_but_not_combined_markets():
    def dc(label, one_or_cross=1110, one_or_two=1220, cross_or_two=1910):
        return _offer(label, "Double Chance", [
            _outcome("OT_ONE_OR_CROSS", one_or_cross), _outcome("OT_ONE_OR_TWO", one_or_two), _outcome("OT_CROSS_OR_TWO", cross_or_two)])

    details = {"betOffers": [
        dc("Double Chance"),
        dc("Double Chance - 1st Half", 1300, 1500, 2100),
        dc("Double Chance and Both Teams To Score"),  # otro mercado: no se emite
        _offer("Double Chance", "Double Chance", [_outcome("OT_ONE_OR_CROSS", 1500)]),  # incompleto
    ]}
    markets = parse_event_offers(details, "Valencia vs. Real Sociedad", "futbol", "paf", HOME, AWAY)
    by_type = {m.market_type: m for m in markets}

    assert _prices(by_type["DC"]) == [("1X", 1.11), ("12", 1.22), ("X2", 1.91)]
    assert _prices(by_type["DC_HT"]) == [("1X", 1.3), ("12", 1.5), ("X2", 2.1)]
    assert sum(1 for m in markets if m.market_type.startswith("DC")) == 2


def test_double_chance_with_a_suspended_selection_is_dropped():
    offer = _offer("Double Chance", "Double Chance", [
        _outcome("OT_ONE_OR_CROSS", 1110), _outcome("OT_ONE_OR_TWO", 1220), _outcome("OT_CROSS_OR_TWO", None, status="SUSPENDED")])
    assert parse_event_offers({"betOffers": [offer]}, "A vs. B", "futbol", "paf", HOME, AWAY) == []
