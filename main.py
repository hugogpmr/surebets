import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from bot.telegram_bot import build_app, notify_opportunity
from engine.scan import run_scan_cycle
from providers.altenar import AltenarProvider
from providers.base import OddsProvider
from providers.betexplorer import BetExplorerProvider
from providers.betfair import BetfairProvider
from providers.cuotasahora import CuotasAhoraProvider
from providers.kambi import KambiProvider
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
    # Segundo comparador (empresa distinta a CuotasAhora/OddsPortal),
    # verificado en vivo 2026-09-17 - ver providers/betexplorer.py. Arranca
    # solo con LaLiga y Champions League (mismas claves "futbol"/
    # "futbol_champions" que el resto), no con todas las competiciones que ya
    # cubre CuotasAhora - ampliar ahí una vez esté estable en producción.
    BetExplorerProvider(),
    # Jokerbet + Pastón + Betway vía la API de la plataforma Altenar (sin
    # navegador): córners, tarjetas, hándicaps y mercados por mitad
    # pre-partido. Solo fútbol de momento - ver providers/altenar.py.
    AltenarProvider(),
    # Paf + LeoVegas vía la API pública de Kambi (otra plataforma B2B, otro
    # feed de precios: permite arbitraje ENTRE plataformas en córners/tarjetas).
    KambiProvider(),
]
# Las ligas/deportes nuevos (top 5 europeas, Copa del Rey, LaLiga2,
# baloncesto y tenis) solo están cubiertos por CuotasAhoraProvider (ver su
# docstring y README.md "Competiciones soportadas"): Sportium/Betfair/
# Winamax ignoran las claves para las que no tienen `competition_urls`.
SPORTS = [
    "futbol",
    "futbol_champions",
    "futbol_premier",
    "futbol_seriea",
    "futbol_bundesliga",
    "futbol_ligue1",
    "futbol_europa_league",
    "futbol_laliga2",
    "futbol_copa_rey",
    "futbol_eredivisie",
    "futbol_liga_portugal",
    "futbol_championship",
    "futbol_mls",
    "futbol_super_lig",
    "futbol_jupiler",
    "futbol_brasileirao",
    "futbol_liga_mx",
    "futbol_liga_argentina",
    "futbol_scotland",
    "futbol_conference_league",
    "futbol_libertadores",
    "futbol_sudamericana",
    "futbol_austria",
    "futbol_suiza",
    "futbol_dinamarca",
    "futbol_polonia",
    "futbol_noruega",
    "futbol_suecia",
    "futbol_croacia",
    "futbol_chequia",
    "baloncesto_acb",
    "baloncesto_euroleague",
    "baloncesto_nba",
    "baloncesto_eurocup",
    "tenis_atp",
    "balonmano_champions",
    "beisbol_mlb",
    "americano_nfl",
]

# Oportunidades activas del ciclo anterior (clave -> {margin, cycles, notified}),
# en memoria: este proceso corre de forma continua (VM + systemd), así que no
# hace falta persistirlo en disco. Ver engine/scan.py para el porqué del dedupe.
_active_opportunities: dict[str, dict] = {}


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
        confirm_cycles=config.CONFIRM_CYCLES,
        round_step=config.ROUND_STEP,
        warn_margin=config.WARN_MARGIN,
        max_margin=config.MAX_MARGIN,
        verify_margin=config.VERIFY_MARGIN,
        verify_cycles=config.VERIFY_CYCLES,
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
