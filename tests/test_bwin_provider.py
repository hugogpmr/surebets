from datetime import datetime, timedelta, timezone

from providers.bwin import BwinProvider, parse_fixture, select_fixtures

HOME_ID, AWAY_ID = 100, 200
HOME, AWAY = "Criciuma EC SC", "Operario PR"
START = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")


def option(name, odds, *types, participant=None, status="Visible"):
    parameters = {"optionTypes": list(types)}
    if participant is not None:
        parameters["fixtureParticipant"] = participant
    return {"name": {"value": name}, "status": status, "price": {"odds": odds}, "parameters": parameters}


def market(name, kind, happening, period, options, status="Visible", **extra):
    params = {"MarketType": kind, "Happening": happening, "Period": period, **extra}
    return {
        "name": {"value": name}, "status": status, "options": options,
        "parameters": [{"key": k, "value": str(v)} for k, v in params.items()],
    }


def three_way(happening="Goal", period="RegularTime", prices=(1.9, 3.1, 4.0), **extra):
    return market("Resultado", "3way", happening, period, [
        option(HOME, prices[0], "Max", participant=HOME_ID),
        option("X", prices[1], "Draw"),
        option(AWAY, prices[2], "Max", participant=AWAY_ID),
    ], **extra)


def view(*markets):
    return {"fixture": {
        "id": "2:1", "startDate": START, "stage": "PreMatch",
        "participants": [
            {"id": HOME_ID, "name": {"value": HOME}, "properties": {"type": "HomeTeam"}},
            {"id": AWAY_ID, "name": {"value": AWAY}, "properties": {"type": "AwayTeam"}},
            {"id": 1, "name": {"value": "Un jugador"}, "properties": {"type": "Player"}},
        ],
        "optionMarkets": list(markets),
    }}


def parsed(*markets):
    return {m.market_type: m for m in parse_fixture(view(*markets))}


def prices(m):
    return [(o.name, o.odds) for o in m.outcomes]


def test_three_way_uses_participant_ids_and_periods_and_metrics():
    markets = parsed(
        three_way(),
        three_way(period="FirstHalf", prices=(2.5, 2.05, 4.33)),
        three_way(happening="Corner", prices=(1.37, 8.75, 3.6)),
        three_way(happening="CombinedCards", prices=(2.6, 4.4, 1.9)),
    )
    assert prices(markets["1X2"]) == [("1", 1.9), ("X", 3.1), ("2", 4.0)]
    assert prices(markets["1X2_HT"])[0] == ("1", 2.5)
    assert prices(markets["CORNERS_1X2"]) == [("1", 1.37), ("X", 8.75), ("2", 3.6)]
    assert "CARDS_1X2" in markets
    assert markets["1X2"].event == "Criciuma EC SC vs. Operario PR" and markets["1X2"].start_time is not None
    assert all(o.bookmaker == "bwin" for o in markets["1X2"].outcomes)


def test_special_variants_are_not_emitted_as_a_plain_one_x_two():
    # "Resultado del partido VA (+2)" paga por adelantado con 2 goles de ventaja: no es un 1X2 normal
    markets = parsed(three_way(MarketSubType="2Up3wayPricing"), three_way(RangeValue="0-3600"))
    assert markets == {}


def test_draw_no_bet_double_chance_btts_and_odd_even():
    markets = parsed(
        market("Ganador sin empate", "DrawNoBet", "Goal", "RegularTime", [
            option(HOME, 1.37, participant=HOME_ID), option(AWAY, 2.85, participant=AWAY_ID)]),
        market("Doble oportunidad", "DoubleChance", "Goal", "RegularTime", [
            option(f"{HOME} o X", 1.22), option(f"X o {AWAY}", 1.8), option(f"{HOME} o {AWAY}", 1.33)]),
        market("Ambos equipos marcan", "BTTS", "Goal", "RegularTime", [option("Sí", 2.0), option("No", 1.7)]),
        market("Total de goles par o impar", "Odd/Even", "Goal", "RegularTime", [option("Impar", 1.88), option("Par", 1.8)]),
        market("Córners par o impar", "Odd/Even", "Corner", "FirstHalf", [option("Impar", 1.83), option("Par", 1.8)]),
    )
    assert prices(markets["DNB"]) == [("1", 1.37), ("2", 2.85)]
    assert prices(markets["DC"]) == [("1X", 1.22), ("X2", 1.8), ("12", 1.33)]
    assert prices(markets["BTTS"]) == [("Yes", 2.0), ("No", 1.7)]
    assert prices(markets["OE"]) == [("Odd", 1.88), ("Even", 1.8)]
    assert "CORNERS_OE_HT" in markets


def test_over_under_lines_periods_teams_and_metrics():
    def ou(happening, period, line, over, under, team=None):
        extra = {"DecimalValue": f"{line:.4f}"}
        if team:
            extra["FixtureParticipant"] = str(team)
        return market("Total", "Over/Under", happening, period, [
            option(f"Más de {line}".replace(".", ","), over, "Over"), option(f"Menos de {line}".replace(".", ","), under, "Under")], **extra)

    markets = parsed(
        ou("Goal", "RegularTime", 2.5, 2.25, 1.55),
        ou("Goal", "RegularTime", 2.0, 1.6, 2.4),
        ou("Goal", "RegularTime", 2.25, 1.9, 1.9),
        ou("Goal", "FirstHalf", 0.5, 1.46, 2.5),
        ou("Goal", "RegularTime", 1.5, 1.8, 1.9, team=HOME_ID),
        ou("Corner", "SecondHalf", 3.5, 2.15, 1.57, team=AWAY_ID),
        ou("CombinedCards", "RegularTime", 5.5, 1.73, 1.9),
    )
    assert prices(markets["OU_2.5"]) == [("Over", 2.25), ("Under", 1.55)]
    assert "OU_2" in markets and "OU_2/2.5" in markets  # línea de cuarto como "dos líneas"
    assert "OU_HT_0.5" in markets and "OU_HOME_1.5" in markets
    assert "CORNERS_OU_AWAY_2H_3.5" in markets and "CARDS_OU_5.5" in markets


def test_asian_handicap_is_expressed_from_the_home_side_and_both_lines_must_agree():
    def handicap(home_line, away_line, period="RegularTime", happening="Goal"):
        return market("Hándicap", "2wayHandicap", happening, period, [
            option(f"{HOME} ({home_line})".replace(".", ","), 1.87, participant=HOME_ID),
            option(f"{AWAY} ({away_line})".replace(".", ","), 1.8, participant=AWAY_ID)])

    markets = parsed(handicap("-0.5", "0.5"), handicap("+1", "-1", period="FirstHalf"), handicap("-1.5", "1"), handicap("-3.5", "3.5", happening="Corner"))
    assert prices(markets["AH_-0.5"]) == [("1", 1.87), ("2", 1.8)]
    assert "AH_HT_+1" in markets and "CORNERS_AH_-3.5" in markets
    assert not any(key.startswith("AH_-1.5") for key in markets)  # -1.5 / +1: incoherente


def test_first_event_markets():
    markets = parsed(
        market("1er equipo en marcar", "XthHappening", "Goal", "RegularTime", [
            option(HOME, 1.66, participant=HOME_ID), option("No hay gol", 7.5), option(AWAY, 2.6, participant=AWAY_ID)], IntegerValue=1),
        market("1er córner", "XthHappening", "Corner", "FirstHalf", [
            option(HOME, 1.47, participant=HOME_ID), option("No hay córners", 41.0), option(AWAY, 2.45, participant=AWAY_ID)], IntegerValue=1),
    )
    assert prices(markets["FIRST_GOAL"]) == [("1", 1.66), ("None", 7.5), ("2", 2.6)]
    assert "CORNERS_FIRST_HT" in markets


def test_markets_with_a_closed_option_or_unknown_labels_are_dropped():
    markets = parsed(
        market("Ambos equipos marcan", "BTTS", "Goal", "RegularTime", [option("Sí", 2.0), option("No", 1.7, status="Suspended")]),
        market("Total", "Over/Under", "Goal", "RegularTime", [option("Más de 2,5", 2.0, "Over"), option("Otra cosa", 1.7)], DecimalValue="2.5000"),
        market("Doble oportunidad", "DoubleChance", "Goal", "RegularTime", [option("Algo raro", 1.2), option("X o Nadie", 1.8), option("Otro", 1.3)]),
        market("Algo", "BTTS", "Goal", "RegularTime", [option("Sí", 2.0), option("No", 1.7)], status="Hidden"),
    )
    assert markets == {}


def test_fixture_without_home_and_away_teams_gives_nothing():
    assert parse_fixture({"fixture": {"startDate": START, "participants": [], "optionMarkets": []}}) == []


def _fixture(fixture_id, hours=6, stage="PreMatch", markets=40, name="A - B", competition="Liga", virtual=False):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": fixture_id, "stage": stage, "isVirtual": virtual, "totalMarketsCount": markets, "startDate": start,
        "name": {"value": name}, "competition": {"name": {"value": competition}}, "region": {"name": {"value": "España"}},
    }


def test_select_fixtures_keeps_prematch_real_men_matches_inside_the_horizon_with_enough_markets():
    fixtures = [
        _fixture("ok"),
        _fixture("live", stage="Live"),
        _fixture("virtual", virtual=True),
        _fixture("far", hours=200),
        _fixture("few", markets=10),
        _fixture("women", name="Chivas (F) - Tigres (F)"),
        _fixture("women2", competition="Liga MX Femenil"),
        _fixture("past", hours=-1),
    ]
    chosen = select_fixtures(fixtures, datetime.now(timezone.utc), timedelta(hours=48), True, True)
    assert [f["id"] for f in chosen] == ["ok"]
    # el filtro de femenino se puede desactivar
    chosen = select_fixtures(fixtures, datetime.now(timezone.utc), timedelta(hours=48), True, False)
    assert {f["id"] for f in chosen} == {"ok", "women", "women2"}


def test_no_football_requested_means_no_browser():
    assert BwinProvider().fetch_markets(["tenis_atp"]) == []
