import asyncio
from datetime import datetime, timedelta, timezone

from engine.alerts import SourceAlerts
from engine.health import SourceHealth
from engine.live import Lane, LaneView, run_detector, run_lane
from providers.base import OddsProvider
from storage.db import export_snapshot
from tests.test_scan_cycle import FakeProvider, db, ou, run  # noqa: F401  (db es un fixture)

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)


async def no_sleep(_seconds):
    await asyncio.sleep(0)


def lane(provider, interval=60, max_age=600):
    return Lane(provider, timedelta(seconds=interval), timedelta(seconds=max_age))


def test_lane_serves_its_last_read_only_while_fresh():
    item = lane(FakeProvider("altenar", []), max_age=600)
    item.markets, item.read_at = [ou("betway", 2.0, 1.8)], NOW
    assert len(LaneView(item, lambda: NOW + timedelta(seconds=599)).fetch_markets([])) == 1
    assert LaneView(item, lambda: NOW + timedelta(seconds=601)).fetch_markets([]) == []
    assert item.status(NOW)["markets"] == 1 and item.status(NOW)["age_seconds"] == 0


def test_lane_keeps_the_previous_read_when_a_read_fails_or_comes_empty():
    provider = FakeProvider("altenar", [], readings=[[ou("betway", 2.0, 1.8)], [], []])
    item = lane(provider)
    updated = asyncio.Event()
    asyncio.run(run_lane(item, [item], ["futbol"], updated, None, None, sleep=no_sleep, max_reads=3, clock=lambda: NOW))
    assert provider.calls == 3 and item.reads == 3
    assert len(item.markets) == 1 and item.read_at == NOW  # la vacía no borra la buena
    assert updated.is_set()


class Broken(OddsProvider):
    name = "sportium"
    uses_browser = True
    parkable = True

    def fetch_markets(self, sports):
        raise RuntimeError("bloqueado")


def test_failing_browser_lane_is_parked_and_alerted_per_read(tmp_path):
    health = SourceHealth(str(tmp_path / "h.json"), park_after=2)
    alerts = SourceAlerts(str(tmp_path / "a.json"), alert_after=2)
    sent = []

    async def admin(text):
        sent.append(text)

    item = lane(Broken())
    asyncio.run(
        run_lane(item, [item], ["futbol"], asyncio.Event(), None, None, health, alerts, admin,
                 sleep=no_sleep, max_reads=2, clock=lambda: NOW)
    )
    assert not item.ok and health.streak("sportium") == 2
    assert health.retry_in("sportium", NOW) is not None  # aparcada
    assert len(sent) == 1 and "sportium" in sent[0]


class Refiner(OddsProvider):
    name = "pokerstars"
    refines = True

    def __init__(self):
        self.peers = None

    def fetch_markets(self, sports):
        return [ou("pokerstars", 2.0, 1.8)]

    def refine(self, sports, peer_markets):
        self.peers = peer_markets
        return [ou("pokerstars", 2.1, 1.7, event="Extra vs. Partido")]


def test_refine_uses_the_other_lanes_fresh_markets():
    other = lane(FakeProvider("altenar", []))
    other.markets, other.read_at = [ou("betway", 2.0, 1.8)], NOW
    refiner = Refiner()
    item = lane(refiner)
    asyncio.run(run_lane(item, [item, other], ["futbol"], asyncio.Event(), None, None, sleep=no_sleep, max_reads=1, clock=lambda: NOW))
    assert refiner.peers == other.markets
    assert len(item.markets) == 2


def test_detector_waits_for_every_lane_before_the_first_analysis():
    fast, slow = lane(FakeProvider("altenar", [])), lane(FakeProvider("zebet", []))
    updated = asyncio.Event()
    seen = []

    async def detect(views):
        seen.append({v.name: v.lane.reads for v in views})

    async def scenario():
        detector = asyncio.create_task(
            run_detector([fast, slow], updated, detect, timedelta(0), max_runs=1, poll_seconds=0.01)
        )
        fast.reads = 1
        updated.set()
        await asyncio.sleep(0.05)
        assert seen == []  # zebet aún no ha leído
        slow.reads = 1
        await asyncio.wait_for(detector, 1)

    asyncio.run(scenario())
    assert seen == [{"altenar": 1, "zebet": 1}]


def test_detector_survives_a_failing_analysis():
    item = lane(FakeProvider("altenar", []))
    item.reads = 1
    updated = asyncio.Event()
    calls = []

    async def detect(views):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("fallo puntual")

    async def scenario():
        detector = asyncio.create_task(run_detector([item], updated, detect, timedelta(0), max_runs=2))
        updated.set()
        await asyncio.sleep(0.01)
        updated.set()
        await asyncio.wait_for(detector, 1)

    asyncio.run(scenario())
    assert len(calls) == 2


def test_high_margin_pending_needs_minimum_age_in_live_mode(db):
    def providers():
        return [FakeProvider("casasdeapuestas", [ou("bet365", 2.5, 1.5), ou("bwin", 1.5, 2.5)])]

    state = {}
    age = timedelta(minutes=30)
    # Muchos análisis seguidos en pocos segundos no bastan...
    for _ in range(5):
        assert run(providers(), db, state, confirm_cycles=1, verify_cycles=3, verify_min_age=age) == []
    assert export_snapshot(db)["comparisons"][0]["verification"] == "pendiente"
    # ...hasta que lleva ese tiempo apareciendo.
    key = next(iter(state))
    state[key]["since"] = (datetime.now(timezone.utc) - age - timedelta(seconds=1)).isoformat()
    sent = run(providers(), db, state, confirm_cycles=1, verify_cycles=3, verify_min_age=age)
    assert len(sent) == 1 and "sin verificar en directo" in sent[0]


def test_run_live_builds_one_lane_per_source_with_its_interval():
    from scripts.run_live import build_lanes

    lanes = {item.name: item for item in build_lanes()}
    assert {"altenar", "kambi", "casasdeapuestas", "pokerstars"} <= set(lanes)
    assert lanes["casasdeapuestas"].interval == timedelta(seconds=120)
    assert lanes["pokerstars"].interval == timedelta(seconds=720)  # navegador: ritmo de siempre
    assert all(item.max_age >= timedelta(minutes=20) for item in lanes.values())
