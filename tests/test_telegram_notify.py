import asyncio
import time

import bot.telegram_bot as telegram_bot
import config
from bot.telegram_bot import notify_opportunity


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, message_thread_id=None):
        self.sent.append(text)


def _run(coro):
    return asyncio.run(coro)


def _no_real_wait(monkeypatch):
    """Sustituye asyncio.sleep por una versión que no espera de verdad pero recuerda
    con qué duración se llamó, para poder comprobarla."""
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(telegram_bot.asyncio, "sleep", fake_sleep)
    return sleeps


def test_no_wait_when_telegram_is_not_configured(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    sleeps = _no_real_wait(monkeypatch)
    bot = FakeBot()
    _run(notify_opportunity(bot, "hola"))
    assert bot.sent == [] and sleeps == []


def test_alert_sent_shortly_after_the_previous_one_waits_the_remaining_gap(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(config, "TELEGRAM_TOPIC_NAME", "")  # sin tema: se salta _notify_thread_id
    monkeypatch.setattr(config, "NOTIFY_MIN_INTERVAL_SECONDS", 3.0)
    # Como si el aviso anterior se hubiera mandado hace 0.2s: quedan ~2.8s de espera.
    telegram_bot._last_sent_at = time.monotonic() - 0.2
    sleeps = _no_real_wait(monkeypatch)

    bot = FakeBot()
    _run(notify_opportunity(bot, "segunda"))

    assert bot.sent == ["segunda"]
    assert len(sleeps) == 1
    assert 2.7 < sleeps[0] < 2.9


def test_first_alert_ever_does_not_wait(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(config, "TELEGRAM_TOPIC_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_MIN_INTERVAL_SECONDS", 3.0)
    telegram_bot._last_sent_at = 0.0  # nunca se ha mandado nada
    sleeps = _no_real_wait(monkeypatch)

    bot = FakeBot()
    _run(notify_opportunity(bot, "primera"))

    assert bot.sent == ["primera"] and sleeps == []


def test_alert_sent_long_after_the_previous_one_does_not_wait(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(config, "TELEGRAM_TOPIC_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_MIN_INTERVAL_SECONDS", 3.0)
    telegram_bot._last_sent_at = time.monotonic() - 10  # hace 10s, de sobra
    sleeps = _no_real_wait(monkeypatch)

    bot = FakeBot()
    _run(notify_opportunity(bot, "segunda"))

    assert bot.sent == ["segunda"] and sleeps == []


def test_last_sent_at_updates_after_sending(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(config, "TELEGRAM_TOPIC_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_MIN_INTERVAL_SECONDS", 3.0)
    telegram_bot._last_sent_at = 0.0
    _no_real_wait(monkeypatch)

    before = time.monotonic()
    _run(notify_opportunity(FakeBot(), "primera"))
    assert telegram_bot._last_sent_at >= before
