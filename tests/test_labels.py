import pytest

from engine.arbitrage import compare_market
from datetime import datetime, timedelta, timezone

from engine.labels import kickoff_line, market_title, outcome_label, split_teams
from engine.models import Market, Outcome
from engine.scan import format_alert

EVENT = "Sevilla vs. Getafe"


@pytest.mark.parametrize(
    "market_type, sport, title",
    [
        ("1X2", "futbol", "Resultado (1X2)"),
        ("1X2_HT", "futbol", "Resultado (1X2) · 1ª parte"),
        ("BTTS", "futbol", "Ambos equipos marcan"),
        ("BTTS_HT", "futbol", "Ambos equipos marcan · 1ª parte"),
        ("BTTS_2H", "futbol", "Ambos equipos marcan · 2ª parte"),
        ("DNB", "futbol", "Empate no apuesta (si empatan, devuelven)"),
        ("DC_HT", "futbol", "Doble oportunidad · 1ª parte"),
        ("OU_2.5", "futbol", "Total de goles: más o menos de 2.5"),
        ("OU_2.5/3", "futbol", "Total de goles: más o menos de 2.5/3"),
        ("OU_HOME_2H_1.5", "futbol", "Total de goles de Sevilla: más o menos de 1.5 · 2ª parte"),
        ("OU_220.5", "baloncesto", "Total de puntos: más o menos de 220.5"),
        ("CORNERS_OU_9.5", "futbol", "Total de córners: más o menos de 9.5"),
        ("CORNERS_OU_AWAY_HT_2.5", "futbol", "Total de córners de Getafe: más o menos de 2.5 · 1ª parte"),
        ("CARDS_OE", "futbol", "Total de tarjetas: impar o par"),
        ("CORNERS_1X2", "futbol", "Más córners"),
        ("CORNERS_FIRST_HT", "futbol", "Primer córner · 1ª parte"),
        ("CORNERS_LAST", "futbol", "Último córner"),
        ("FIRST_GOAL_2H", "futbol", "Primer gol · 2ª parte"),
        ("AH_-0.5/-1", "futbol", "Hándicap asiático"),
        ("CORNERS_AH_HT_-1.5", "futbol", "Hándicap asiático de córners · 1ª parte"),
        ("EH_-1", "futbol", "Hándicap europeo (Sevilla -1)"),
        ("CS_HOME", "futbol", "Sevilla mantiene la portería a cero"),
        ("WTN_AWAY", "futbol", "Getafe gana sin encajar gol"),
        ("WIN_ANY_HALF_HOME", "futbol", "Sevilla gana alguna de las partes"),
        ("SCORE_BOTH_HALVES_AWAY", "futbol", "Getafe marca en las dos partes"),
        ("PENALTY", "futbol", "Hay penalti en el partido"),
        ("FIRST_SHOT_ON_TARGET", "futbol", "Primer tiro a puerta"),
    ],
)
def test_market_title(market_type, sport, title):
    assert market_title(market_type, EVENT, sport) == title


@pytest.mark.parametrize(
    "market_type, outcome, label",
    [
        ("1X2", "1", "Sevilla"),
        ("1X2", "X", "Empate"),
        ("1X2", "2", "Getafe"),
        ("BTTS_HT", "Yes", "Sí"),
        ("BTTS_HT", "No", "No"),
        ("OE", "Odd", "Impar"),
        ("OU_2.5", "Over", "Más de 2.5"),
        ("CORNERS_OU_9.5", "Under", "Menos de 9.5"),
        ("DC", "1X", "Sevilla o empate"),
        ("DC", "12", "Sevilla o Getafe"),
        ("DC", "X2", "Empate o Getafe"),
        ("AH_-1.5", "1", "Sevilla -1.5"),
        ("AH_-1.5", "2", "Getafe +1.5"),
        ("AH_0.5/1", "1", "Sevilla +0.5/+1"),
        ("AH_0.5/1", "2", "Getafe -0.5/-1"),
        ("AH_0/-0.5", "2", "Getafe 0/+0.5"),
        ("FIRST_GOAL", "None", "Ninguno"),
        ("CORNERS_FIRST", "1", "Sevilla"),
    ],
)
def test_outcome_label(market_type, outcome, label):
    assert outcome_label(market_type, outcome, EVENT, "futbol") == label


def test_unknown_market_falls_back_to_raw_code():
    assert market_title("ALGO_RARO", EVENT, "futbol") == "ALGO_RARO"
    assert outcome_label("ALGO_RARO", "Z", EVENT, "futbol") == "Z"


def test_split_teams_fallback():
    assert split_teams("Sevilla - Getafe") == ("Sevilla", "Getafe")
    assert split_teams("sin separador") == ("Local", "Visitante")


def test_format_alert_is_readable_spanish():
    market = Market(
        event=EVENT,
        sport="futbol",
        market_type="BTTS_HT",
        outcomes=[
            Outcome(name="Yes", bookmaker="sportium", odds=2.4),
            Outcome(name="No", bookmaker="bwin", odds=1.9),
        ],
    )
    text = format_alert(compare_market(market, 100.0))
    assert "Nueva surebet · Fútbol" in text
    assert "Ambos equipos marcan · 1ª parte" in text
    assert "sportium: Sí @2.40" in text
    assert "bwin: No @1.90" in text
    assert "BTTS" not in text
    assert "fiabilidad" not in text.lower()
    assert "€" not in text


def test_kickoff_line():
    assert kickoff_line(None) == "🕐 Fecha y hora del partido no disponibles"
    now = datetime.now(timezone.utc)
    assert "(en 3.0 h)" in kickoff_line(now + timedelta(hours=3, seconds=30))
    assert "(en 20 min)" in kickoff_line(now + timedelta(minutes=20, seconds=30))
    assert kickoff_line(now - timedelta(hours=1)).startswith("🕐 Empezó ")
