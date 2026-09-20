import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from engine.models import Market, Outcome
from engine.scan import normalize_state, run_scan_cycle
from providers.base import OddsProvider
from storage.db import export_snapshot, init_db

LOGGER = logging.getLogger("test")


class FakeProvider(OddsProvider):
    def __init__(self, name, markets):
        self.name = name
        self._markets = markets

    def fetch_markets(self, sports):
        return self._markets


def ou(bookmaker, over, under, event="Ajax vs. Feyenoord", start=None):
    return Market(
        event=event,
        sport="futbol",
        market_type="OU_2.5",
        outcomes=[Outcome("Over", bookmaker, over), Outcome("Under", bookmaker, under)],
        start_time=start,
    )


def run(providers, db, state, **kwargs):
    sent = []

    async def notify(text):
        sent.append(text)

    asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, state, notify=notify, logger=LOGGER, **kwargs)
    )
    return sent


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    return path


def surebet_providers(start=None):
    # betway Over 2.30 + paf Under 2.10 -> 1/2.3 + 1/2.1 = 0.911 (margen ~8,9 %)... usamos algo más fino:
    return [
        FakeProvider("altenar", [ou("betway", 2.10, 1.80, start=start)]),
        FakeProvider("kambi", [ou("paf", 1.80, 2.05, start=start)]),
    ]


def test_surebet_is_only_notified_after_confirm_cycles(db):
    state = {}
    first = run(surebet_providers(), db, state, confirm_cycles=2)
    assert first == []  # primera vez: pendiente de confirmar
    assert state and next(iter(state.values()))["cycles"] == 1

    second = run(surebet_providers(), db, state, confirm_cycles=2)
    assert len(second) == 1
    assert "betway" in second[0] and "paf" in second[0]

    third = run(surebet_providers(), db, state, confirm_cycles=2)
    assert third == []  # ya avisada, mismo margen: sin repetir


def test_surebet_that_disappears_must_be_confirmed_again(db):
    state = {}
    run(surebet_providers(), db, state, confirm_cycles=2)
    run([FakeProvider("altenar", [ou("betway", 1.80, 1.80)])], db, state, confirm_cycles=2)
    assert state == {}
    assert run(surebet_providers(), db, state, confirm_cycles=2) == []


def test_default_confirm_cycles_keeps_old_behaviour(db):
    assert len(run(surebet_providers(), db, {})) == 1


def test_alert_shows_kickoff_sources_and_rounded_stakes(db):
    start = datetime.now(timezone.utc) + timedelta(hours=5)
    (text,) = run(surebet_providers(start), db, {}, round_step=5.0)
    assert "Empieza" in text
    assert "betway←altenar" in text and "paf←kambi" in text
    stakes = [line for line in text.splitlines() if "€ a " in line]
    assert stakes and all(float(line.split(":")[1].split("€")[0]) % 5 == 0 for line in stakes)


def test_comparator_only_surebet_is_flagged_in_alert_and_snapshot(db):
    providers = [
        FakeProvider("cuotasahora", [ou("bet365", 2.10, 1.80), ou("bwin", 1.80, 2.05)]),
    ]
    (text,) = run(providers, db, {})
    assert "fiabilidad baja" in text and "comparadores" in text
    snapshot = export_snapshot(db)
    row = snapshot["comparisons"][0]
    assert row["is_surebet"] and row["reliability"] == "baja" and "solo_comparador" in row["flags"]
    assert {o["source"] for o in row["odds"]} == {"cuotasahora"}
    assert row["surebet_since"]


def test_data_errors_are_discarded_not_notified(db):
    # BTTS con una sola pata (bug real del estado guardado): margen 13 % falso.
    broken = Market("Boca vs. Vasco", "futbol", "BTTS", [Outcome("Yes", "bet365", 7.0)])
    sent = run([FakeProvider("cuotasahora", [broken])], db, {})
    assert sent == []
    snapshot = export_snapshot(db)
    row = snapshot["comparisons"][0]
    assert not row["is_surebet"] and "mercado_incompleto" in row["flags"]
    assert snapshot["recent_opportunities"] == []


def test_blocked_rows_sink_below_real_comparisons_in_snapshot(db):
    broken = Market("Boca vs. Vasco", "futbol", "BTTS", [Outcome("Yes", "bet365", 7.0)])
    fine = ou("betway", 1.95, 1.95, event="Ajax vs. Feyenoord")
    run([FakeProvider("altenar", [broken, fine])], db, {})
    events = [c["event"] for c in export_snapshot(db)["comparisons"]]
    assert events == ["Ajax vs. Feyenoord", "Boca vs. Vasco"]


def test_legacy_state_format_is_normalised():
    state = normalize_state({"a||futbol||OU_2.5||paf,betway": 0.05, "b": {"margin": 0.02, "cycles": 3, "notified": True}})
    assert state["a||futbol||OU_2.5||paf,betway"] == {"margin": 0.05, "cycles": 1, "notified": True}
    assert state["b"]["cycles"] == 3


def test_init_db_migrates_an_old_comparisons_table(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE comparisons (key TEXT PRIMARY KEY, event TEXT NOT NULL, sport TEXT NOT NULL,
               market_type TEXT NOT NULL, bookmakers TEXT NOT NULL, margin REAL NOT NULL,
               is_surebet INTEGER NOT NULL, odds_json TEXT NOT NULL, guaranteed_profit REAL,
               first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)"""
        )
    init_db(path)
    init_db(path)  # idempotente
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(comparisons)")}
    assert {"start_time", "flags_json", "reliability", "surebet_since"} <= columns
