"""Un solo ciclo de escaneo, pensado para correr como job programado de GitHub
Actions (ver .github/workflows/scan.yml) en vez de como proceso de larga duración.

Diferencia clave con main.py: aquí no hay proceso continuo ni Application de
python-telegram-bot con polling (no hace falta para solo enviar avisos), y el
estado de "oportunidades activas" para el dedupe se carga/guarda en un JSON en
disco (data/active_opportunities.json) porque cada ejecución de Actions es un
runner nuevo que no recuerda nada del anterior; ese JSON se commitea de vuelta
al repo al final del workflow.

Efecto colateral de este modo "solo avisos": los comandos /hoy, /ahora y
/stats del bot (bot/telegram_bot.py) no responden aquí, porque necesitan un
proceso escuchando permanentemente los mensajes de Telegram. Documentado en
deploy/README_DEPLOY.md.

Al final de cada ciclo también vuelca el estado a docs/data.json (ver
storage.db.export_snapshot), que el workflow commitea junto al resto y que
alimenta el panel web estático servido por GitHub Pages desde docs/.

Modos (`--mode`):
- `full` (por defecto, el de GitHub Actions): lee todas las fuentes en un mismo
  ciclo. Con las 38 competiciones de los comparadores tarda horas.
- `fast`: lee solo las fuentes directas (Sportium, Betfair, Winamax, bwin, Altenar,
  Kambi, en paralelo; ~1-2 min) y le suma los comparadores desde la caché en disco. Es el
  que corre cada pocos minutos en local (scripts/local_scan.ps1).
- `slow`: lee los comparadores (CuotasAhora, BetExplorer) por rotación de
  competiciones durante un presupuesto de tiempo y actualiza la caché; no
  calcula surebets ni avisa (scripts/local_slow_scan.ps1). Ver engine/cache.py.
"""

import argparse
import asyncio
import json
import logging
import pathlib
from datetime import timedelta

from telegram import Bot

import config
from engine.cache import CachedProvider, ComparatorCache, refresh_cache
from engine.scan import normalize_state, run_scan_cycle
from providers.altenar import AltenarProvider
from providers.base import OddsProvider
from providers.betexplorer import BetExplorerProvider
from providers.bet777 import Bet777Provider
from providers.betfair import BetfairProvider
from providers.bwin import BwinProvider
from providers.cuotasahora import CuotasAhoraProvider
from providers.kambi import KambiProvider
from providers.sportium import SportiumProvider
from providers.winamax import WinamaxProvider
from storage.db import export_snapshot, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("surebets.action")

def direct_providers() -> tuple[list[OddsProvider], list[OddsProvider]]:
    """(antes, después): fuentes directas de la casa. Se devuelven en dos grupos
    para conservar el orden histórico (los comparadores van en medio: la primera
    fuente que lista un partido fija el nombre del evento en el cruce)."""
    return (
        # Winamax (socket de su web) y bwin (API de su web): cientos de mercados por partido,
        # incluidos hándicap asiático y mercados por mitad (bwin también córners y tarjetas).
        [SportiumProvider(), BetfairProvider(), WinamaxProvider(), BwinProvider()],
        [
            # Jokerbet + Pastón + Betway vía la API de Altenar (córners, tarjetas,
            # hándicaps, mercados por mitad pre-partido; solo fútbol de momento).
            AltenarProvider(),
            # Paf + LeoVegas vía la API pública de Kambi (otra plataforma B2B, otro
            # feed de precios: permite arbitraje ENTRE plataformas en córners/tarjetas).
            KambiProvider(),
            # Bet777 vía la API de su plataforma Sportify (cuotas de FeedConstruct): tercera
            # fuente de precios distinta de Altenar y Kambi. Goles, hándicap asiático y
            # mitades; sin córners ni tarjetas.
            Bet777Provider(),
        ],
    )


def comparator_providers(max_matches: int | None = None) -> list[OddsProvider]:
    return [
        CuotasAhoraProvider(max_matches=max_matches),
        # Segundo comparador (empresa distinta a CuotasAhora/OddsPortal),
        # verificado en vivo 2026-09-17 - ver providers/betexplorer.py. Solo cubre
        # LaLiga y Champions League, no todas las competiciones de CuotasAhora.
        BetExplorerProvider(),
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

STATE_PATH = pathlib.Path("data/active_opportunities.json")
SNAPSHOT_PATH = pathlib.Path("docs/data.json")


def run_slow() -> None:
    """Ciclo lento: actualiza la caché de los comparadores. No toca la base de
    datos, ni el panel, ni Telegram."""
    cache = ComparatorCache(config.COMPARATOR_CACHE_PATH)
    done = refresh_cache(
        comparator_providers(config.SLOW_MAX_MATCHES),
        SPORTS,
        cache,
        timedelta(minutes=config.SLOW_BUDGET_MINUTES),
        logger,
    )
    logger.info("Ciclo lento terminado: %d competiciones actualizadas", len(done))


async def run_scan(mode: str) -> None:
    pathlib.Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.DB_PATH)

    before, after = direct_providers()
    if mode == "fast":
        cache = ComparatorCache(config.COMPARATOR_CACHE_PATH)
        max_age = timedelta(hours=config.COMPARATOR_MAX_AGE_HOURS)
        middle: list[OddsProvider] = [CachedProvider(p.name, cache, max_age) for p in comparator_providers()]
    else:
        middle = comparator_providers()
    providers = before + middle + after

    active_state: dict[str, dict] = {}
    if STATE_PATH.exists():
        active_state = normalize_state(json.loads(STATE_PATH.read_text(encoding="utf-8")))

    bot = Bot(config.TELEGRAM_BOT_TOKEN)

    async def notify(text: str) -> None:
        if config.TELEGRAM_CHAT_ID:
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)

    result = await run_scan_cycle(
        providers,
        SPORTS,
        config.BANKROLL,
        config.MIN_MARGIN,
        config.DB_PATH,
        active_state,
        notify=notify,
        logger=logger,
        confirm_cycles=config.CONFIRM_CYCLES,
        round_step=config.ROUND_STEP,
        warn_margin=config.WARN_MARGIN,
        max_margin=config.MAX_MARGIN,
        verify_margin=config.VERIFY_MARGIN,
        verify_cycles=config.VERIFY_CYCLES,
    )

    # Estado de cada fuente en el panel/snapshot: una con 0 mercados, o vacía en
    # la caché, es señal de que algo va mal. De las cacheadas se añade su edad.
    sources = result["sources"]
    for provider in middle:
        if isinstance(provider, CachedProvider) and provider.name in sources:
            sources[provider.name]["cache"] = provider.summary

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(active_state, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = export_snapshot(
        config.DB_PATH,
        settings={
            "mode": mode,
            "confirm_cycles": config.CONFIRM_CYCLES,
            "round_step": config.ROUND_STEP,
            "warn_margin": config.WARN_MARGIN,
            "verify_margin": config.VERIFY_MARGIN,
            "max_margin": config.MAX_MARGIN,
            "verify_cycles": config.VERIFY_CYCLES,
            "sources": sources,
        },
    )
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=("full", "fast", "slow"), default="full")
    args = parser.parse_args()
    if args.mode == "slow":
        run_slow()
    else:
        asyncio.run(run_scan(args.mode))


if __name__ == "__main__":
    main()
