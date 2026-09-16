import json
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from engine.arbitrage import format_stakes
from storage.db import get_opportunities_since, get_stats


def format_opportunity(row) -> str:
    stakes = json.loads(row["stakes_json"])
    return (
        f"🎯 {row['event']} ({row['sport']}, {row['market_type']})\n"
        f"   Casas: {row['bookmakers']}\n"
        f"   Margen: {row['margin'] * 100:.2f}% | "
        f"Banca: {row['total_stake']}€ | Beneficio: {row['guaranteed_profit']}€\n"
        f"{format_stakes(stakes)}"
    )


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
        f"Margen medio: {s['avg_margin'] * 100:.2f}%\n"
        f"Beneficio potencial acumulado: {s['total_potential_profit']}€"
    )


def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("hoy", hoy))
    app.add_handler(CommandHandler("ahora", ahora))
    app.add_handler(CommandHandler("stats", stats))
    return app


async def notify_opportunity(app: Application, text: str) -> None:
    if config.TELEGRAM_CHAT_ID:
        await app.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)
