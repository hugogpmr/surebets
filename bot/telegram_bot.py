import json
import os
from datetime import datetime, timedelta, timezone

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from engine.labels import kickoff_line, market_title, outcome_label, sport_name
from storage.db import get_opportunities_since, get_stats


def _row_odds(row) -> dict[str, float]:
    """Cuota de cada pata ("casa:resultado" -> cuota). Las oportunidades
    guardadas antes de registrar las cuotas no la tienen: se recupera de los
    importes, porque cada pata apuesta stake = banca / (cuota * (1 - margen))."""
    raw = row["odds_json"] if "odds_json" in row.keys() else None
    if raw:
        return json.loads(raw)
    stakes = json.loads(row["stakes_json"])
    return {key: round(row["total_stake"] / (amount * (1 - row["margin"])), 2) for key, amount in stakes.items()}


def _row_start_time(row) -> datetime | None:
    raw = row["start_time"] if "start_time" in row.keys() else None
    return datetime.fromisoformat(raw) if raw else None


def format_opportunity(row) -> str:
    """Un emoji por línea (evento, mercado, hora, margen, cada pata), al estilo
    de los mensajes reenviados del grupo origen (ver telegram_source/relay.py y
    su MENSAJE de ejemplo en tests/test_relay.py: "📈 ROI ...\\n🏠 Winamax\\n💵
    Cuota @...") para que ambos tipos de aviso se vean del mismo estilo."""
    event, sport, market_type = row["event"], row["sport"], row["market_type"]
    lines = [
        f"🎯 {event} · {sport_name(sport)}",
        f"📌 {market_title(market_type, event, sport)}",
        kickoff_line(_row_start_time(row)),
        f"📈 Margen {row['margin'] * 100:.2f}%",
    ]
    for key, odds in _row_odds(row).items():
        bookmaker, outcome = key.split(":", 1)
        lines.append(f"🏠 {bookmaker}: {outcome_label(market_type, outcome, event, sport)} @{odds:.2f}")
    return "\n".join(lines)


async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = get_opportunities_since(config.DB_PATH, since)
    if not rows:
        await update.message.reply_text("No se han detectado surebets hoy todavía.")
        return
    text = "\n\n".join(format_opportunity(r) for r in rows[:10])
    await update.message.reply_text(text)


async def ahora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    since = datetime.now(timezone.utc) - timedelta(minutes=15)
    rows = get_opportunities_since(config.DB_PATH, since)
    if not rows:
        await update.message.reply_text("No hay surebets activas en los últimos 15 minutos.")
        return
    text = "\n\n".join(format_opportunity(r) for r in rows[:10])
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = get_stats(config.DB_PATH, days=7)
    await update.message.reply_text(
        f"📊 Últimos {s['period_days']} días\n"
        f"Surebets detectadas: {s['count']}\n"
        f"Margen medio: {s['avg_margin'] * 100:.2f}%"
    )


def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("hoy", hoy))
    app.add_handler(CommandHandler("ahora", ahora))
    app.add_handler(CommandHandler("stats", stats))
    return app


def _load_topic_id() -> int | None:
    try:
        with open(config.TELEGRAM_TOPIC_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f).get("thread_id")
    except (OSError, ValueError):
        return None


def _save_topic_id(thread_id: int) -> None:
    path = config.TELEGRAM_TOPIC_CACHE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"thread_id": thread_id}, f)


async def _notify_thread_id(bot: Bot) -> int | None:
    """Id del tema donde van los avisos (config.TELEGRAM_TOPIC_NAME): se crea la
    primera vez y se cachea en disco para no recrearlo en cada aviso."""
    if not config.TELEGRAM_TOPIC_NAME:
        return None
    cached = _load_topic_id()
    if cached:
        return cached
    topic = await bot.create_forum_topic(chat_id=config.TELEGRAM_CHAT_ID, name=config.TELEGRAM_TOPIC_NAME)
    _save_topic_id(topic.message_thread_id)
    return topic.message_thread_id


async def notify_opportunity(bot: Bot, text: str) -> None:
    if not config.TELEGRAM_CHAT_ID:
        return
    thread_id = await _notify_thread_id(bot)
    await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text, message_thread_id=thread_id)
