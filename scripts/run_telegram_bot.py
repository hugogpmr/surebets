"""Proceso independiente que solo atiende /hoy, /ahora y /stats en Telegram.

Pensado para la VM (systemd, ver deploy/): el escaneo en sí lo hacen los
temporizadores de scan_once_action.py --mode fast/slow (mismo patrón que
scripts/local_scan.ps1 y scripts/local_slow_scan.ps1 en Windows), que escriben
en config.DB_PATH. Este proceso no escanea nada, solo mantiene la conexión de
Telegram abierta (polling) para responder leyendo esa misma base de datos -
ver bot/telegram_bot.py, cuyos handlers ya son de solo lectura.

Los avisos automáticos de cada surebet nueva los manda scan_once_action.py
directamente (notify_opportunity), no este proceso.
"""

import asyncio
import logging

import config
from bot.telegram_bot import build_app
from storage.db import init_db

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("surebets.bot")


async def main() -> None:
    init_db(config.DB_PATH)
    app = build_app()
    async with app:
        await app.start()
        await app.updater.start_polling()
        logger.info("Bot escuchando /hoy /ahora /stats (DB_PATH=%s)", config.DB_PATH)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
