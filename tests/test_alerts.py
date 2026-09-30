import asyncio

import bot.telegram_bot as telegram_bot
import config
from engine.alerts import SourceAlerts

OK = {"ok": True, "markets": 10}
DEAD = {"ok": True, "markets": 0}
FAILED = {"ok": False, "markets": 0}


def make(tmp_path, **kwargs):
    return SourceAlerts(str(tmp_path / "a.json"), **{"alert_after": 3, **kwargs})


def test_alerts_once_after_n_bad_cycles_and_not_again(tmp_path):
    alerts = make(tmp_path)
    assert alerts.update({"sportium": DEAD}) is None
    assert alerts.update({"sportium": FAILED}) is None
    text = alerts.update({"sportium": DEAD})
    assert text and "sportium" in text and "🔴" in text
    assert alerts.update({"sportium": DEAD}) is None  # ya avisó: no repite cada ciclo


def test_one_good_cycle_resets_the_streak(tmp_path):
    alerts = make(tmp_path)
    alerts.update({"bwin": DEAD})
    alerts.update({"bwin": DEAD})
    alerts.update({"bwin": OK})
    assert alerts.update({"bwin": DEAD}) is None  # vuelve a empezar desde 1


def test_announces_recovery_after_an_alert(tmp_path):
    alerts = make(tmp_path)
    for _ in range(3):
        alerts.update({"kambi": FAILED})
    text = alerts.update({"kambi": OK})
    assert text and "🟢" in text and "kambi" in text
    assert alerts.update({"kambi": OK}) is None


def test_several_sources_go_in_one_message(tmp_path):
    alerts = make(tmp_path, alert_after=1)
    text = alerts.update({"a": DEAD, "b": FAILED, "c": OK})
    assert "a" in text and "b" in text and text.count("🔴") == 1


def test_parked_and_ignored_sources_do_not_count(tmp_path):
    alerts = make(tmp_path, alert_after=1, ignore=frozenset({"betfair_exchange"}))
    assert alerts.update({"betfair_exchange": DEAD, "versus": {**DEAD, "parked": True}}) is None


def test_state_survives_between_runs_and_zero_disables(tmp_path):
    make(tmp_path).update({"x": DEAD})
    make(tmp_path).update({"x": DEAD})
    assert make(tmp_path).update({"x": DEAD}) is not None
    assert make(tmp_path, alert_after=0).update({"y": DEAD}) is None


def test_notify_admin_is_silent_without_channel_and_never_raises(monkeypatch):
    class Boom:
        async def send_message(self, **kwargs):
            raise RuntimeError("telegram caído")

    monkeypatch.setattr(config, "ADMIN_ALERT_CHAT_ID", "")
    asyncio.run(telegram_bot.notify_admin(Boom(), "hola"))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHAT_ID", "-100123")
    asyncio.run(telegram_bot.notify_admin(Boom(), "hola"))

