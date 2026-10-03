from datetime import datetime, timedelta, timezone

from engine.models import Market, Outcome
from engine.throttle import ThrottledProvider
from providers.base import OddsProvider

T0 = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
EVERY = timedelta(minutes=19)


class FakeBrowserSource(OddsProvider):
    name = "zebet"
    uses_browser = True
    parkable = True

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def fetch_markets(self, sports):
        self.calls += 1
        return self.result


def market(read_at=T0):
    return Market(event="A vs. B", sport="futbol", market_type="1X2",
                  outcomes=[Outcome(name="1", bookmaker="zebet", odds=2.0)], fetched_at=read_at)


def test_reads_every_third_cycle_and_serves_the_saved_reading_in_between(tmp_path):
    path = str(tmp_path / "throttled_zebet.pkl")
    first = ThrottledProvider(FakeBrowserSource([market()]), EVERY, path, now=T0)
    assert first.uses_browser and first.name == "zebet" and first.parkable
    assert len(first.fetch_markets(["futbol"])) == 1

    for minutes in (7, 14):
        inner = FakeBrowserSource([market(T0 + timedelta(minutes=minutes))])
        skipped = ThrottledProvider(inner, EVERY, path, now=T0 + timedelta(minutes=minutes))
        assert not skipped.uses_browser  # no hace cola en el semáforo de navegadores
        served = skipped.fetch_markets(["futbol"])
        assert inner.calls == 0
        assert served[0].fetched_at == T0  # conserva la hora real de la lectura

    inner = FakeBrowserSource([market(T0 + timedelta(minutes=21))])
    third = ThrottledProvider(inner, EVERY, path, now=T0 + timedelta(minutes=21))
    assert third.uses_browser
    third.fetch_markets(["futbol"])
    assert inner.calls == 1


def test_failed_or_empty_reading_is_not_saved_so_the_next_cycle_reads_again(tmp_path):
    path = str(tmp_path / "throttled_zebet.pkl")
    ThrottledProvider(FakeBrowserSource([market()]), EVERY, path, now=T0).fetch_markets(["futbol"])
    late = T0 + timedelta(minutes=21)
    assert ThrottledProvider(FakeBrowserSource([]), EVERY, path, now=late).fetch_markets(["futbol"]) == []
    retry = ThrottledProvider(FakeBrowserSource([market(late)]), EVERY, path, now=late + timedelta(minutes=7))
    assert retry.due


def test_corrupt_file_means_read_now(tmp_path):
    path = tmp_path / "throttled_zebet.pkl"
    path.write_bytes(b"no es un pickle")
    assert ThrottledProvider(FakeBrowserSource([market()]), EVERY, str(path), now=T0).due
