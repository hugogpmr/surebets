import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from bot.telegram_bot import build_app, notify_opportunity
from engine.scan import run_scan_cycle
from providers.base import OddsProvider
from providers.betfair import BetfairProvider
from providers.cuotasahora import CuotasAhoraProvider
from providers.sportium import SportiumProvider
from providers.winamax import WinamaxProvider
from storage.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("surebets")

# providers/kirolbet.py está implementado pero bloqueado por Akamai (ver README
# "Estado real de los scrapers") - no se activa aquí hasta tener una vía sin
# evasión activa, o decidir explícitamente construirla.
PROVIDERS: list[OddsProvider] = [
    SportiumProvider(),
    BetfairProvider(),
    WinamaxProvider(),
    CuotasAhoraProvider(),
]
SPORTS = ["futbol"]

# Oportunidades activas del ciclo anterior (clave -> margen), en memoria: este
# proceso corre de forma continua (VM + systemd), así que no hace falta
# persistirlo en disco. Ver engine/scan.py para el porqué del dedupe.
_active_opportunities: dict[str, float] = {}


async def scan_once(app) -> None:
    await run_scan_cycle(
        PROVIDERS,
        SPORTS,
        config.BANKROLL,
        config.MIN_MARGIN,
        config.DB_PATH,
        _active_opportunities,
        notify=lambda text: notify_opportunity(app, text),
        logger=logger,
    )


async def main() -> None:
    init_db(config.DB_PATH)
    app = build_app()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(scan_once, "interval", seconds=config.FETCH_INTERVAL_SECONDS, args=[app])
    scheduler.start()

    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
