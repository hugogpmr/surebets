import sqlite3

from bot.telegram_bot import format_opportunity
from engine.arbitrage import compare_market
from engine.models import Market, Outcome
from storage.db import get_opportunities_since, init_db, save_opportunity

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _comparison(start_time=None):
    market = Market(
        event="Sevilla vs. Getafe",
        sport="futbol",
        market_type="BTTS_HT",
        outcomes=[
            Outcome(name="Yes", bookmaker="sportium", odds=2.4),
            Outcome(name="No", bookmaker="bwin", odds=1.9),
        ],
        start_time=start_time,
    )
    return compare_market(market, 250.0)


def _rows(db):
    return get_opportunities_since(db, datetime.now(timezone.utc) - timedelta(minutes=1))


def test_saved_opportunity_is_shown_in_the_new_format(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    save_opportunity(db, _comparison())
    (row,) = _rows(db)
    text = format_opportunity(row)
    assert text.splitlines() == [
        "🎯 Sevilla vs. Getafe · Fútbol",
        "📌 Ambos equipos marcan · 1ª parte",
        "🕐 Fecha y hora del partido no disponibles",
        "📈 Margen 5.70%",
        "🏠 sportium: Sí @2.40",
        "🏠 bwin: No @1.90",
    ]
    assert "€" not in text


def test_old_row_without_odds_recovers_them_from_the_stakes(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    save_opportunity(db, _comparison())
    with sqlite3.connect(db) as conn:  # como una fila guardada antes de existir odds_json
        conn.execute("UPDATE opportunities SET odds_json = NULL")
    (row,) = _rows(db)
    text = format_opportunity(row)
    assert "sportium: Sí @2.40" in text and "bwin: No @1.90" in text


def test_init_db_adds_odds_column_to_an_old_opportunities_table(tmp_path):
    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE opportunities (id INTEGER PRIMARY KEY AUTOINCREMENT, detected_at TEXT NOT NULL,
               event TEXT NOT NULL, sport TEXT NOT NULL, market_type TEXT NOT NULL, bookmakers TEXT NOT NULL,
               margin REAL NOT NULL, total_stake REAL NOT NULL, guaranteed_profit REAL NOT NULL,
               stakes_json TEXT NOT NULL, executed INTEGER NOT NULL DEFAULT 0)"""
        )
    init_db(db)
    save_opportunity(db, _comparison())
    assert len(_rows(db)) == 1


def test_saved_start_time_is_shown_with_date_and_hour(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    start = datetime.now(timezone.utc) + timedelta(hours=5)
    save_opportunity(db, _comparison(start))
    (row,) = _rows(db)
    local = start.astimezone(ZoneInfo("Europe/Madrid"))
    assert f"🕐 Empieza {local:%d/%m %H:%M} (en " in format_opportunity(row)
