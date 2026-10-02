import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from engine.models import Market, Outcome
from engine.scan import normalize_state, run_scan_cycle
from providers.base import OddsProvider
from storage.db import export_snapshot, init_db

LOGGER = logging.getLogger("test")


class FakeProvider(OddsProvider):
    """`markets` puede ser una lista (siempre lo mismo) o, con `readings`, una
    lista de listas: una por llamada (para simular que la cuota cambia entre la
    primera lectura y la de verificación)."""

    def __init__(self, name, markets, fast_recheck=False, readings=None):
        self.name = name
        self.fast_recheck = fast_recheck
        self._markets = markets
        self._readings = list(readings) if readings else None
        self.calls = 0

    def fetch_markets(self, sports):
        self.calls += 1
        if self._readings:
            return self._readings[min(self.calls, len(self._readings)) - 1]
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


def test_notify_failure_does_not_crash_the_cycle_and_retries_next_time(db):
    # Un fallo de red mandando el aviso (Telegram caído, timeout...) no debe tumbar el
    # resto del ciclo: la surebet ya se guarda en la base de datos, y como el aviso no
    # llegó de verdad, no se marca "notified" - debe reintentarse en el próximo ciclo.
    async def failing_notify(text):
        raise TimeoutError("simulated Telegram timeout")

    state = {}
    asyncio.run(
        run_scan_cycle(
            surebet_providers(), ["futbol"], 250.0, 0.01, db, state,
            notify=failing_notify, logger=LOGGER, confirm_cycles=1,
        )
    )
    key = next(iter(state))
    assert state[key]["notified"] is False  # el aviso falló: no se da por avisada
    row = export_snapshot(db)["comparisons"][0]
    assert row["is_surebet"]  # pero sí quedó guardada en la base de datos

    # Un ciclo posterior con un notify que sí funciona debe reintentar el aviso.
    sent = run(surebet_providers(), db, state, confirm_cycles=1)
    assert len(sent) == 1
    assert state[key]["notified"] is True


def test_surebet_that_disappears_must_be_confirmed_again(db):
    state = {}
    run(surebet_providers(), db, state, confirm_cycles=2)
    run([FakeProvider("altenar", [ou("betway", 1.80, 1.80)])], db, state, confirm_cycles=2)
    assert state == {}
    assert run(surebet_providers(), db, state, confirm_cycles=2) == []


def test_default_confirm_cycles_keeps_old_behaviour(db):
    assert len(run(surebet_providers(), db, {})) == 1


def test_alert_shows_kickoff_sources_and_odds(db):
    start = datetime.now(timezone.utc) + timedelta(hours=5)
    (text,) = run(surebet_providers(start), db, {}, round_step=5.0)
    assert "Empieza" in text
    assert "betway←altenar" in text and "paf←kambi" in text
    # El aviso da la cuota de cada casa, sin importes ni beneficio.
    assert "@" in text
    assert "€" not in text and "Beneficio" not in text


def test_comparator_only_surebet_is_flagged_in_alert_and_snapshot(db):
    providers = [
        FakeProvider("cuotasahora", [ou("bet365", 2.10, 1.80), ou("bwin", 1.80, 2.05)]),
    ]
    (text,) = run(providers, db, {})
    assert "fiabilidad" not in text and "comparadores" in text
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


def direct_pair(over, under, fast=True, readings_a=None, readings_b=None):
    """betway (altenar) + paf (kambi): con 2.5/2.5 el margen es un 20 %."""
    a = FakeProvider("altenar", [ou("betway", over, 1.5)], fast_recheck=fast, readings=readings_a)
    b = FakeProvider("kambi", [ou("paf", 1.5, under)], fast_recheck=fast, readings=readings_b)
    return a, b


def test_high_margin_confirmed_by_a_second_direct_read_is_notified_at_once(db):
    a, b = direct_pair(2.5, 2.5)
    sent = run([a, b], db, {}, confirm_cycles=2)
    assert a.calls == 2 and b.calls == 2  # segunda lectura de las dos fuentes directas
    assert len(sent) == 1 and "verificado con una segunda lectura" in sent[0]
    row = export_snapshot(db)["comparisons"][0]
    assert row["is_surebet"] and row["verification"] == "verificada" and "margen_verificado" in row["flags"]
    assert row["reliability"] == "alta"


def test_high_margin_that_vanishes_on_the_second_read_is_dropped(db):
    # primera lectura: Over a 2.5 (margen 20 %); en la segunda la casa ya lo bajó
    a, b = direct_pair(
        2.5, 2.5, readings_a=[[ou("betway", 2.5, 1.5)], [ou("betway", 1.6, 1.5)]]
    )
    sent = run([a, b], db, {}, confirm_cycles=1)
    assert sent == []
    row = export_snapshot(db)["comparisons"][0]
    assert not row["is_surebet"]


def test_high_margin_from_comparators_is_pending_until_verify_cycles(db):
    def providers():
        return [FakeProvider("cuotasahora", [ou("bet365", 2.5, 1.5), ou("bwin", 1.5, 2.5)])]

    state = {}
    assert run(providers(), db, state, confirm_cycles=2, verify_cycles=3) == []
    assert run(providers(), db, state, confirm_cycles=2, verify_cycles=3) == []  # ya cumpliría confirm_cycles
    row = export_snapshot(db)["comparisons"][0]
    assert row["is_surebet"] and row["verification"] == "pendiente"  # visible en el panel
    third = run(providers(), db, state, confirm_cycles=2, verify_cycles=3)
    assert len(third) == 1 and "sin verificar en directo" in third[0]


def test_mixed_sources_high_margin_cannot_be_verified_in_scan(db):
    direct = FakeProvider("kambi", [ou("paf", 1.5, 2.5)], fast_recheck=True)
    comparator = FakeProvider("cuotasahora", [ou("bet365", 2.5, 1.5)])
    assert run([comparator, direct], db, {}, confirm_cycles=1, verify_cycles=2) == []
    assert direct.calls == 2  # se releyó la directa, pero la pata del comparador queda sin verificar
    assert export_snapshot(db)["comparisons"][0]["verification"] == "pendiente"


def test_margin_above_maximum_is_discarded_and_not_rechecked(db):
    a = FakeProvider("altenar", [ou("betway", 3.0, 1.5)], fast_recheck=True)
    b = FakeProvider("kambi", [ou("paf", 1.5, 3.0)], fast_recheck=True)  # margen 33 %
    assert run([a, b], db, {}, confirm_cycles=1) == []
    assert a.calls == 1 and b.calls == 1
    row = export_snapshot(db)["comparisons"][0]
    assert not row["is_surebet"] and "margen_absurdo" in row["flags"]


def test_normal_margin_never_triggers_a_second_read(db):
    a, b = direct_pair(2.1, 2.05)
    run([a, b], db, {}, confirm_cycles=1)
    assert a.calls == 1 and b.calls == 1


def test_mirrored_comparator_table_is_not_reported_as_a_surebet(db):
    # Caso real del estado del 2026-09-17: el comparador ensenaba en la pestana BTTS
    # las columnas 1 y X del 1X2 (2.55 y 3.85), lo que parece una surebet del 35 %.
    one_x_two = Market(
        "Willem II vs. Sittard", "futbol", "1X2",
        [Outcome("1", "bet365", 2.55), Outcome("X", "versus", 3.85), Outcome("2", "paf", 2.63)],
    )
    btts = Market(
        "Willem II vs. Sittard", "futbol", "BTTS", [Outcome("Yes", "bet365", 2.55), Outcome("No", "versus", 3.85)]
    )
    sent = run([FakeProvider("cuotasahora", [one_x_two, btts])], db, {}, confirm_cycles=1, verify_cycles=1, max_margin=0.9)
    assert sent == []
    rows = {r["market_type"]: r for r in export_snapshot(db)["comparisons"]}
    assert "lectura_duplicada" in rows["BTTS"]["flags"] and not rows["BTTS"]["is_surebet"]
    assert "lectura_duplicada" not in rows["1X2"]["flags"]


def test_same_surebet_from_direct_sources_is_never_treated_as_a_mirror(db):
    # Altenar y Kambi devuelven cada mercado por separado: no aplica la defensa
    one = Market("A vs. B", "futbol", "1X2", [Outcome("1", "betway", 2.1), Outcome("X", "paf", 3.4), Outcome("2", "paf", 3.6)])
    ou = Market("A vs. B", "futbol", "OU_2.5", [Outcome("Over", "betway", 2.1), Outcome("Under", "paf", 3.4)])
    sent = run([FakeProvider("kambi", [one, ou])], db, {}, confirm_cycles=1)
    rows = {r["market_type"]: r for r in export_snapshot(db)["comparisons"]}
    assert "lectura_duplicada" not in rows["OU_2.5"]["flags"]


def btts_ht_group():
    """Una sola pata atípica: bet365 'Yes' a 3.25 y retabet 'No' a 2.22 (el 'No' normal
    ronda 1.3) da un margen del 24 %. La fila de retabet es coherente por sí sola
    (1/1.6 + 1/2.22 > 1), así que la limpieza de filas imposibles no la quita y es la
    comprobación de cuotas atípicas la que la descarta."""
    rows = [("bet365", 3.25, 1.30), ("888sport", 3.0, 1.32), ("paf", 3.1, 1.31), ("versus", 2.95, 1.33), ("retabet", 1.6, 2.22)]
    outcomes = []
    for bookmaker, yes, no in rows:
        outcomes += [Outcome("Yes", bookmaker, yes), Outcome("No", bookmaker, no)]
    return Market("Preston vs. Millwall", "futbol", "BTTS_HT", outcomes)


def test_comparator_leg_far_from_the_other_books_is_discarded_not_notified(db):
    sent = run([FakeProvider("cuotasahora", [btts_ht_group()])], db, {}, confirm_cycles=1, verify_cycles=1)
    assert sent == []
    row = export_snapshot(db)["comparisons"][0]
    assert not row["is_surebet"] and "cuota_atipica" in row["flags"] and row["reliability"] == "baja"


def test_direct_leg_far_from_the_others_is_kept_with_a_warning(db):
    overs = [Outcome("Over", "leovegas", 2.6), Outcome("Under", "leovegas", 1.3)]  # cuota directa muy alta
    others = [Outcome(n, b, o) for b, ov, un in (("bet365", 1.9, 1.95), ("888sport", 1.88, 1.97), ("bwin", 1.92, 1.93))
              for n, o in (("Over", ov), ("Under", un))]
    under = [Outcome("Over", "paf", 1.8), Outcome("Under", "paf", 2.05)]
    direct = Market("A vs. B", "futbol", "OU_2.5", overs + under)
    comparators = Market("A vs. B", "futbol", "OU_2.5", others)
    sent = run([FakeProvider("cuotasahora", [comparators]), FakeProvider("kambi", [direct])], db, {}, confirm_cycles=1, verify_cycles=1)
    row = export_snapshot(db)["comparisons"][0]
    assert row["is_surebet"] and "cuota_destacada" in row["flags"] and "cuota_atipica" not in row["flags"]
    assert row["reliability"] in ("media", "baja")  # nunca "alta" con una cuota tan destacada
    assert len(sent) == 1 and "muy por encima de lo que pagan las demás casas" in sent[0]


def all_rows_impossible_group():
    """Caso real del 2026-09-21 (Preston vs. Millwall, BTTS 1ª parte): las 6 casas del
    comparador con Yes ~3.1 / No ~2.2 -> cada casa suma 0.78 de probabilidad, algo que
    ninguna casa ofrece: la tabla entera era la de otra pestaña."""
    rows = [("bet365", 3.25, 2.2), ("888sport", 3.1, 2.2), ("codere", 3.05, 2.15), ("paf", 3.05, 2.12), ("retabet", 3.23, 2.22)]
    outcomes = []
    for bookmaker, yes, no in rows:
        outcomes += [Outcome("Yes", bookmaker, yes), Outcome("No", bookmaker, no)]
    return Market("Preston vs. Millwall", "futbol", "BTTS_HT", outcomes)


def test_a_comparator_table_whose_every_row_is_impossible_disappears(db):
    sent = run([FakeProvider("cuotasahora", [all_rows_impossible_group()])], db, {}, confirm_cycles=1, verify_cycles=1)
    assert sent == []
    assert export_snapshot(db)["comparisons"] == []  # ni siquiera se muestra como comparación


def test_only_the_impossible_rows_are_dropped_and_the_coherent_ones_still_compare(db):
    good = [Outcome(n, b, o) for b, y, no in (("bet365", 2.1, 1.75), ("paf", 2.0, 1.9)) for n, o in (("Yes", y), ("No", no))]
    bad = [Outcome("Yes", "retabet", 3.2), Outcome("No", "retabet", 2.2)]  # suma 0.77: lectura errónea
    provider = FakeProvider("cuotasahora", [Market("A vs. B", "futbol", "BTTS", good + bad)])
    sent = run([provider], db, {}, confirm_cycles=1, verify_cycles=1)
    (row,) = export_snapshot(db)["comparisons"]
    assert {o["bookmaker"] for o in row["odds"]} == {"bet365", "paf"}  # retabet ya no cuenta
    assert not row["is_surebet"] and sent == []


class SlowProvider(FakeProvider):
    def __init__(self, name, delay, fail=False, browser=True):
        super().__init__(name, [])
        self.delay = delay
        self.fail = fail
        self.uses_browser = browser

    def fetch_markets(self, sports):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return []


def test_cycle_reports_read_time_per_source_and_phase_times(db):
    async def notify(text):
        pass

    result = asyncio.run(
        run_scan_cycle(
            [SlowProvider("a", 0.3), SlowProvider("b", 0.3), SlowProvider("c", 0.05, fail=True)],
            ["futbol"], 250.0, 0.01, db, {}, notify=notify, logger=LOGGER,
            max_concurrency=1,
        )
    )
    sources = result["sources"]
    # Con un solo turno, la 2ª fuente en leer espera a la 1ª: su lectura dura lo mismo,
    # pero el tiempo de espera lo separa (si no, parecería que esa fuente es lenta).
    assert all(sources[n]["seconds"] >= 0.04 for n in "abc")
    assert sources["a"]["seconds"] < 0.6 and sources["b"]["seconds"] < 0.6
    assert max(sources[n]["wait_seconds"] for n in "abc") >= 0.3
    assert sources["c"]["ok"] is False and sources["c"]["seconds"] >= 0.04  # el fallo también se mide
    assert {"lectura", "cruce", "verificacion", "avisos", "guardado_bd", "total"} <= result["phases"].keys()
    assert result["phases"]["lectura"] >= 0.6 and result["phases"]["total"] >= result["phases"]["lectura"]


class RefiningProvider(FakeProvider):
    refines = True

    def __init__(self, name, markets, extra):
        super().__init__(name, markets)
        self._extra = extra
        self.peer_books = None

    def refine(self, sports, peer_markets):
        self.peer_books = sorted({o.bookmaker for m in peer_markets for o in m.outcomes})
        return self._extra


def run_cycle(providers, db, **kwargs):
    async def notify(text):
        pass

    return asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, {}, notify=notify, logger=LOGGER, **kwargs)
    )


def test_second_pass_gets_only_the_other_sources_and_its_markets_join_the_first(db):
    refiner = RefiningProvider("pokerstars", [ou("pokerstars", 1.9, 1.9)], extra=[ou("pokerstars", 2.0, 2.0, event="Extra vs. Mercado")])
    other = FakeProvider("paf", [ou("paf", 1.8, 2.1)])
    result = run_cycle([refiner, other], db)
    assert refiner.peer_books == ["paf"]  # no se ve a sí mismo
    assert result["sources"]["pokerstars"]["markets"] == 2  # 1.ª pasada + extra
    assert "segunda_pasada" in result["phases"]


def test_failing_second_pass_keeps_the_first_pass_markets(db):
    class Broken(RefiningProvider):
        def refine(self, sports, peer_markets):
            raise RuntimeError("boom")

    broken = Broken("pokerstars", [ou("pokerstars", 1.9, 1.9)], extra=[])
    result = run_cycle([broken, FakeProvider("paf", [ou("paf", 1.8, 2.1)])], db)
    assert result["sources"]["pokerstars"]["ok"] is True and result["sources"]["pokerstars"]["markets"] == 1


def test_second_pass_is_not_run_when_the_first_pass_failed(db):
    class FailingFirstPass(RefiningProvider):
        def fetch_markets(self, sports):
            raise RuntimeError("bloqueado")

    provider = FailingFirstPass("pokerstars", [], extra=[ou("pokerstars", 2.0, 2.0)])
    result = run_cycle([provider, FakeProvider("paf", [ou("paf", 1.8, 2.1)])], db)
    assert result["sources"]["pokerstars"]["ok"] is False
    assert provider.peer_books is None  # refine() no llegó a llamarse


def test_parkable_source_is_skipped_after_repeated_failures_and_reported_as_parked(db, tmp_path):
    from engine.health import SourceHealth

    class Blocked(FakeProvider):
        parkable = True

        def fetch_markets(self, sports):
            self.calls += 1
            return []  # bloqueada: vacía, sin excepción

    blocked = Blocked("sportium", [])
    health = SourceHealth(str(tmp_path / "h.json"), park_after=3)
    for _ in range(3):
        result = run_cycle([blocked, FakeProvider("paf", [ou("paf", 1.8, 2.1)])], db, health=health)
        assert "parked" not in result["sources"]["sportium"]
    assert blocked.calls == 3

    result = run_cycle([blocked, FakeProvider("paf", [ou("paf", 1.8, 2.1)])], db, health=health)
    assert blocked.calls == 3  # esta vez no se ha leído
    assert result["sources"]["sportium"]["parked"] is True and result["sources"]["sportium"]["retry_in_minutes"] > 0
    assert result["sources"]["paf"]["ok"] is True  # el resto sigue igual


def test_non_parkable_source_is_never_parked_even_if_always_empty(db, tmp_path):
    from engine.health import SourceHealth

    quiet = FakeProvider("winamax", [])
    health = SourceHealth(str(tmp_path / "h.json"), park_after=2)
    for _ in range(5):
        run_cycle([quiet], db, health=health)
    assert quiet.calls == 5


def _quiet_notify(text):
    return asyncio.sleep(0)


def test_http_sources_start_at_once_even_with_more_sources_than_default_pool_threads(db):
    # El pool por defecto de asyncio tiene min(32, cpus + 4) hilos (6 en la VM de 2 vCPU):
    # con 12 fuentes de 0,3 s, las 6 últimas empezaban tras las primeras (>= 0,6 s en total)
    # y aparecían como "lentas" en el log. Con hilo propio para cada una, todas a la vez.
    providers = [SlowProvider(f"http{i}", 0.3, browser=False) for i in range(12)]
    started = time.perf_counter()
    result = asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify, logger=LOGGER,
                       max_concurrency=1)  # el límite de navegadores no les afecta
    )
    assert time.perf_counter() - started < 0.55
    assert all(info["wait_seconds"] < 0.15 and 0.28 <= info["seconds"] < 0.5 for info in result["sources"].values())


def test_max_concurrency_only_limits_browser_sources(db):
    providers = [SlowProvider(f"nav{i}", 0.3, browser=True) for i in range(4)] + [SlowProvider("http", 0.3, browser=False)]
    result = asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify, logger=LOGGER,
                       max_concurrency=2)
    )
    waits = sorted(info["wait_seconds"] for info in result["sources"].values())
    assert waits[2] < 0.15  # la fuente http y los 2 navegadores que entran no esperan
    assert waits[-1] >= 0.28  # los otros 2 navegadores esperan turno
    assert result["sources"]["http"]["wait_seconds"] < 0.15
    assert result["phases"]["lectura"] >= 0.6


class EarlyRefiner(RefiningProvider):
    def __init__(self, name, markets, extra):
        super().__init__(name, markets, extra)
        self.refined_at = None

    def refine(self, sports, peer_markets):
        self.refined_at = time.perf_counter()
        return super().refine(sports, peer_markets)


class LateProvider(FakeProvider):
    def __init__(self, name, markets, delay):
        super().__init__(name, markets)
        self.delay = delay
        self.finished_at = None

    def fetch_markets(self, sports):
        time.sleep(self.delay)
        self.finished_at = time.perf_counter()
        return self._markets


def test_second_pass_starts_early_from_previous_cycle_peers_and_falls_back_without_them(db, tmp_path):
    from engine.peers import PeerEvents

    events = [f"Equipo{i} vs. Rival{i}" for i in range(25)]
    peers = PeerEvents(str(tmp_path / "peers.json"))
    peers.save([ou("paf", 1.8, 2.1, event=e) for e in events], datetime.now(timezone.utc))

    def cycle(peer_store):
        refiner = EarlyRefiner("pokerstars", [ou("pokerstars", 1.9, 1.9)], extra=[ou("pokerstars", 2.0, 2.0, event="Nuevo vs. Mercado")])
        slow = LateProvider("altenar", [ou("altenar", 1.8, 2.1)], delay=0.5)
        result = asyncio.run(
            run_scan_cycle([refiner, slow], ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify,
                           logger=LOGGER, peers=peer_store)
        )
        return refiner, slow, result

    # Con datos del ciclo anterior: la 2.ª pasada corre MIENTRAS la fuente lenta sigue leyendo,
    # y ve a las casas del ciclo anterior (no a las de este ciclo).
    refiner, slow, result = cycle(peers)
    assert refiner.refined_at < slow.finished_at
    assert refiner.peer_books == ["paf"]
    assert "segunda_pasada" not in result["phases"] and result["sources"]["pokerstars"]["markets"] == 2

    # Sin ellos (primer ciclo): espera a las demás fuentes, como antes.
    refiner, slow, result = cycle(PeerEvents(str(tmp_path / "no_existe.json")))
    assert refiner.refined_at >= slow.finished_at
    assert refiner.peer_books == ["altenar"] and "segunda_pasada" in result["phases"]


def test_cycle_saves_what_the_other_sources_listed_but_not_the_refiner_itself(db, tmp_path):
    from engine.peers import PeerEvents

    store = PeerEvents(str(tmp_path / "peers.json"))
    refiner = RefiningProvider("pokerstars", [ou("pokerstars", 1.9, 1.9, event="Solo PS vs. Nadie")], extra=[])
    other = FakeProvider("paf", [ou("paf", 1.8, 2.1, event=f"A{i} vs. B{i}") for i in range(30)])
    asyncio.run(run_scan_cycle([refiner, other], ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify,
                               logger=LOGGER, peers=store))
    loaded = store.load(datetime.now(timezone.utc))
    assert len(loaded) == 30 and all(m.event != "Solo PS vs. Nadie" for m in loaded)


class BrowserProvider(FakeProvider):
    uses_browser = True

    def __init__(self, name, markets, log):
        super().__init__(name, markets)
        self.log = log

    def fetch_markets(self, sports):
        self.log.append(("lee", self.name))
        time.sleep(0.05)
        return self._markets


class BrowserRefiner(BrowserProvider):
    refines = True

    def refine(self, sports, peer_markets):
        self.log.append(("segunda", self.name))
        time.sleep(0.05)
        return []


def test_browser_turns_go_longest_first_by_last_cycle_times(db):
    log = []
    providers = [BrowserProvider(n, [ou(n, 1.9, 1.9)], log) for n in ("corta", "nueva", "larga")]
    result = asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify, logger=LOGGER,
                       max_concurrency=1, expected_seconds={"larga": 120.0, "corta": 15.0})
    )
    assert log == [("lee", "larga"), ("lee", "corta"), ("lee", "nueva")]
    assert list(result["sources"]) == ["corta", "nueva", "larga"]  # el orden de la lista no cambia


def test_early_second_pass_keeps_its_browser_turn(db, tmp_path):
    # Antes soltaba el turno entre las dos pasadas y la segunda volvía a la cola detrás de las demás
    from engine.peers import PeerEvents

    peers = PeerEvents(str(tmp_path / "peers.json"))
    peers.save([ou("paf", 1.8, 2.1, event=f"E{i} vs. R{i}") for i in range(25)], datetime.now(timezone.utc))
    log = []
    refiner = BrowserRefiner("pokerstars", [ou("pokerstars", 1.9, 1.9)], log)
    other = BrowserProvider("zebet", [ou("zebet", 1.8, 2.1)], log)
    asyncio.run(
        run_scan_cycle([refiner, other], ["futbol"], 250.0, 0.01, db, {}, notify=_quiet_notify, logger=LOGGER,
                       max_concurrency=1, peers=peers)
    )
    assert log == [("lee", "pokerstars"), ("segunda", "pokerstars"), ("lee", "zebet")]
