import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys

import pytest

from engine.backtest import SurebetLog, _connect
from engine.scan import run_scan_cycle
from storage.db import init_db
from tests.test_scan_cycle import FakeProvider, ou

LOGGER = logging.getLogger("test")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FailingProvider(FakeProvider):
    def fetch_markets(self, sports):
        raise RuntimeError("fuente caída")


@pytest.fixture
def log(tmp_path):
    return SurebetLog(str(tmp_path / "backtest.db"))


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    return path


def cycle(providers, db, state, log):
    async def notify(text):
        pass

    asyncio.run(
        run_scan_cycle(
            providers, ["futbol"], 250.0, 0.01, db, state,
            notify=notify, logger=LOGGER, backtest=log,
        )
    )


def surebet(over_betway=2.10, event="Ajax vs. Feyenoord"):
    # betway Over + paf Under: 1/2.10 + 1/2.05 = 0.964 (margen ~3,6 %)
    return [
        FakeProvider("altenar", [ou("betway", over_betway, 1.80, event=event)]),
        FakeProvider("kambi", [ou("paf", 1.80, 2.05, event=event)]),
    ]


def episodes(log):
    with _connect(log.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM episodes ORDER BY id").fetchall()


def test_a_surebet_is_one_episode_across_cycles_and_remembers_the_odds(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    cycle(surebet(), db, state, log)
    (episode,) = episodes(log)
    assert episode["status"] == "abierta"
    assert episode["cycles"] == 2
    assert episode["notified"] == 1
    assert episode["discarded"] == 0
    assert episode["has_comparator_leg"] == 0
    legs = {leg["leg"]: leg for leg in json.loads(episode["legs_json"])}
    assert legs["betway:Over"]["odds_first"] == 2.10
    assert legs["paf:Under"]["odds_last"] == 2.05


def test_odds_that_move_close_the_episode_as_a_real_move_not_an_error(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    cycle(surebet(over_betway=1.85), db, state, log)  # betway baja la cuota: ya no hay arbitraje
    (episode,) = episodes(log)
    assert episode["status"] == "cerrada"
    assert episode["end_reason"] == "cuota_movida"
    legs = {leg["leg"]: leg for leg in json.loads(episode["legs_json"])}
    assert legs["betway:Over"]["odds_last"] == 2.10
    assert legs["betway:Over"]["odds_end"] == 1.85
    assert legs["paf:Under"]["odds_end"] == 2.05


def test_market_that_vanishes_is_not_reported_as_a_move(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    cycle(surebet(event="Otro vs. Partido"), db, state, log)  # el partido ya no sale
    (episode,) = [e for e in episodes(log) if e["event"] == "Ajax vs. Feyenoord"]
    assert episode["end_reason"] == "mercado_desaparecido"


def test_one_missed_source_cycle_does_not_split_the_episode(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    cycle([FakeProvider("altenar", [ou("betway", 2.10, 1.80)]), FailingProvider("kambi", [])], db, state, log)
    (episode,) = episodes(log)
    assert episode["status"] == "abierta" and episode["missed"] == 1

    cycle(surebet(), db, state, log)  # vuelve la fuente: es el mismo episodio
    (episode,) = episodes(log)
    assert episode["status"] == "abierta" and episode["missed"] == 0 and episode["cycles"] == 2


def test_source_down_for_several_cycles_closes_as_no_data_not_as_a_move(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    for _ in range(3):
        cycle([FakeProvider("altenar", [ou("betway", 2.10, 1.80)]), FailingProvider("kambi", [])], db, state, log)
    (episode,) = episodes(log)
    assert episode["status"] == "cerrada"
    assert episode["end_reason"] == "sin_datos"


def test_a_data_error_is_logged_as_discarded(db, log):
    # Una sola casa con Over 2.2 / Under 2.2: margen 9 % pero todas las patas de la misma casa.
    cycle([FakeProvider("altenar", [ou("betway", 2.2, 2.2)])], db, {}, log)
    (episode,) = episodes(log)
    assert episode["discarded"] == 1
    assert "una_sola_casa" in json.loads(episode["flags_json"])
    assert episode["notified"] == 0


def test_another_house_taking_over_a_leg_is_a_relay_not_a_move(db, log):
    state = {}
    cycle(surebet(), db, state, log)
    better = surebet() + [FakeProvider("bet777", [ou("bet777", 1.70, 2.20)])]  # mejor Under que paf
    cycle(better, db, state, log)
    first, second = episodes(log)
    assert first["end_reason"] == "relevo_de_casas"
    assert second["status"] == "abierta" and "bet777" in second["bookmakers"]


def test_a_failure_saving_the_history_never_breaks_the_cycle(db, tmp_path):
    broken = SurebetLog(str(tmp_path / "b.db"))
    broken.path = str(tmp_path)  # un directorio: ya no se puede abrir como base de datos
    cycle(surebet(), db, {}, broken)  # no debe lanzar


def test_history_is_optional(db):
    cycle(surebet(), db, {}, None)


def test_report_runs_on_a_real_history_and_exports_csv(db, log, tmp_path):
    state = {}
    cycle(surebet(), db, state, log)
    cycle(surebet(over_betway=1.85), db, state, log)
    csv_path = tmp_path / "e.csv"
    result = subprocess.run(
        [sys.executable, "scripts/backtest_report.py", "--db", log.path, "--csv", str(csv_path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "cuota_movida" in result.stdout
    assert "betway" in result.stdout
    assert "Ajax vs. Feyenoord" in csv_path.read_text(encoding="utf-8-sig")
