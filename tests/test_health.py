from datetime import datetime, timedelta, timezone

from engine.health import SourceHealth

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def bad(health, name, times, start=T0, step=timedelta(minutes=12)):
    for i in range(times):
        health.record(name, good=False, now=start + step * i)


def test_source_is_read_normally_until_it_fails_park_after_times_in_a_row(tmp_path):
    health = SourceHealth(str(tmp_path / "h.json"), park_after=5)
    bad(health, "sportium", 4)
    assert health.retry_in("sportium", T0 + timedelta(hours=1)) is None  # 4 < 5: aún se lee siempre
    bad(health, "sportium", 1, start=T0 + timedelta(minutes=48))
    assert health.retry_in("sportium", T0 + timedelta(minutes=49)) is not None  # 5.ª: aparcada


def test_parked_source_backs_off_and_doubles_the_wait_up_to_six_hours(tmp_path):
    health = SourceHealth(str(tmp_path / "h.json"), park_after=2)
    now = T0
    waits = []
    for _ in range(7):
        health.record("bwin", good=False, now=now)
        if health.streak("bwin") >= 2:
            waits.append(health.retry_in("bwin", now))
            now += waits[-1]  # el momento justo en que toca reintentar
    assert [int(w.total_seconds() // 60) for w in waits] == [30, 60, 120, 240, 360, 360]
    assert health.retry_in("bwin", now - timedelta(minutes=1)) is not None
    assert health.retry_in("bwin", now) is None  # pasada la espera vuelve a leerse


def test_one_good_reading_unparks_completely(tmp_path):
    health = SourceHealth(str(tmp_path / "h.json"), park_after=3)
    bad(health, "versus", 6)
    assert health.retry_in("versus", T0 + timedelta(minutes=72)) is not None
    health.record("versus", good=True, now=T0 + timedelta(hours=8))
    assert health.streak("versus") == 0
    bad(health, "versus", 2, start=T0 + timedelta(hours=9))
    assert health.retry_in("versus", T0 + timedelta(hours=9, minutes=30)) is None  # vuelve a contar desde 0


def test_park_after_zero_disables_parking(tmp_path):
    health = SourceHealth(str(tmp_path / "h.json"), park_after=0)
    bad(health, "betfair", 50)
    assert health.retry_in("betfair", T0 + timedelta(hours=1)) is None


def test_state_survives_between_processes_and_is_per_source(tmp_path):
    path = str(tmp_path / "cache" / "h.json")  # la carpeta no existe aún
    first = SourceHealth(path, park_after=2)
    bad(first, "sportium", 3)
    first.save()
    second = SourceHealth(path, park_after=2)
    assert second.streak("sportium") == 3
    assert second.retry_in("sportium", T0 + timedelta(minutes=25)) is not None
    assert second.retry_in("winamax", T0) is None


def test_corrupt_file_does_not_break_the_scan(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{no es json", encoding="utf-8")
    health = SourceHealth(str(path), park_after=2)
    assert health.retry_in("sportium", T0) is None
    health.record("sportium", good=False, now=T0)
    health.save()
    assert SourceHealth(str(path), park_after=2).streak("sportium") == 1
