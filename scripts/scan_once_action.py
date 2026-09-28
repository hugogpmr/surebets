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
- `slow`: lee el comparador (CasasDeApuestas; BetExplorer retirado 2026-09-28, ver
  `comparator_providers`) por rotación de competiciones durante un presupuesto de
  tiempo y actualiza la caché; no calcula surebets ni avisa
  (scripts/local_slow_scan.ps1). Ver engine/cache.py.
"""

import argparse
import asyncio
import json
import logging
import pathlib
import time
from datetime import timedelta

from telegram import Bot

import config
from bot.telegram_bot import notify_opportunity
from engine.cache import CachedProvider, ComparatorCache, refresh_cache
from engine.health import SourceHealth
from engine.peers import PeerEvents
from engine.scan import normalize_state, run_scan_cycle
from providers.altenar import AltenarProvider
from providers.base import OddsProvider
from providers.bet777 import Bet777Provider
from providers.betfair import BetfairProvider
from providers.betfair_exchange import BetfairExchangeProvider
from providers.bwin import BwinProvider
from providers.casasdeapuestas import CasasDeApuestasProvider
from providers.kambi import KambiProvider
from providers.marcaapuestas import MarcaApuestasProvider
from providers.pokerstars import PokerStarsProvider
from providers.sport888 import Sport888Provider
from providers.sportium import SportiumProvider
from providers.versus import VersusProvider
from providers.williamhill import WilliamHillProvider
from providers.winamax import WinamaxProvider
from providers.zebet import ZebetProvider
from storage.db import export_snapshot, init_db

logging.basicConfig(level=logging.INFO)
# httpx registra en INFO cada petición con su URL completa; la de Telegram lleva el
# token del bot (api.telegram.org/bot<TOKEN>/...) y acabaría en logs/*.log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("surebets.action")

def direct_providers() -> tuple[list[OddsProvider], list[OddsProvider]]:
    """(antes, después): fuentes directas de la casa. Se devuelven en dos grupos
    para conservar el orden histórico (los comparadores van en medio: la primera
    fuente que lista un partido fija el nombre del evento en el cruce)."""
    return (
        # Winamax (socket de su web) y bwin (API de su web): cientos de mercados por partido,
        # incluidos hándicap asiático y mercados por mitad (bwin también córners y tarjetas).
        # PokerStars: solo 1X2 por DOM (su API JSON está detrás de Akamai, ver
        # providers/pokerstars.py), plataforma propia (no Altenar/Kambi/Sportify).
        # Marca Apuestas: mismo framework "ta-" que Sportium (mismo vendor de
        # frontend), verificado en vivo el 2026-09-23 tras confirmar con Playwright
        # headless real que su antiguo bloqueo de Cloudflare ya no aplica (ver
        # estudio_tecnicas_otros_bots.md) - 1X2, over/under, BTTS y 1X2_HT.
        # Zebet: plataforma propia del grupo Zeturf, verificada en vivo el
        # 2026-09-24 con Playwright headless real (antes "sin confirmar" en
        # checklist.md por el mismo motivo que Interwetten/Retabet: el navegador
        # interactivo no basta como señal) - solo 1X2 de LaLiga por ahora, ver
        # providers/zebet.py.
        # 888sport: API JSON propia (plataforma Spectate), leída con un fetch()
        # DESDE la página ya cargada del navegador (una petición suelta da 403) -
        # mismo patrón que bwin. Solo 1X2 de LaLiga por ahora, ver providers/sport888.py.
        # Versus: mismo framework "ta-" que Sportium/Marca Apuestas (mismo backend,
        # códigos internos de mercado BTSC/H1RS idénticos, solo cambian los nombres
        # de ítem del desplegable) - 1X2, Goles Totales, Ambos Marcan y Resultado al
        # descanso. Ver providers/versus.py.
        [
            SportiumProvider(),
            BetfairProvider(),
            WinamaxProvider(),
            BwinProvider(),
            PokerStarsProvider(),
            MarcaApuestasProvider(),
            ZebetProvider(),
            Sport888Provider(),
            VersusProvider(),
        ],
        [
            # Jokerbet + Pastón + Betway vía la API de Altenar: fútbol (córners,
            # tarjetas, hándicaps, mercados por mitad) y, desde 2026-09-24,
            # baloncesto (hándicap/total/par-impar por cuarto y mitad, incl.
            # prórroga) y tenis (hándicap/total de juegos y sets, por set) - antes
            # esas dos claves solo las cubría CuotasAhoraProvider (1X2 vía comparador).
            AltenarProvider(),
            # Paf + LeoVegas vía la API pública de Kambi (otra plataforma B2B, otro
            # feed de precios: permite arbitraje ENTRE plataformas). Mismos tres
            # deportes que Altenar desde 2026-09-24.
            KambiProvider(),
            # Bet777 vía la API de su plataforma Sportify (cuotas de FeedConstruct): tercera
            # fuente de precios distinta de Altenar y Kambi. Goles, hándicap asiático y
            # mitades; sin córners ni tarjetas.
            Bet777Provider(),
            # William Hill vía su propia API JSON (plataforma OpenBet), sin navegador. Solo
            # 1X2 por ahora; el bloqueo de IP de datacenter/VPN es solo de la web, esta API
            # responde igual sin cookies (ver providers/williamhill.py).
            WilliamHillProvider(),
            # Betfair Exchange API oficial (Delayed App Key gratuita), aparte del scraper DOM
            # de la web de apuestas fijas (BetfairProvider): otro precio del mismo operador,
            # útil como referencia "sharp" adicional. Opcional y sin verificar en vivo todavía
            # (hace falta una app key + cuenta que solo el usuario puede generar/dar) - sin
            # BETFAIR_APP_KEY/USERNAME/PASSWORD en .env se salta sola, ver providers/betfair_exchange.py.
            BetfairExchangeProvider(),
        ],
    )


def comparator_providers(max_matches: int | None = None) -> list[OddsProvider]:
    return [
        # CuotasAhoraProvider retirado 2026-09-27 (decisión del usuario, ver
        # conversación): CasasDeApuestasProvider (abajo) ya cubre las mismas 12 casas de
        # su ALLOWED_BOOKMAKERS más 14 casas adicionales, muchas más competiciones
        # (descubiertas solas, no una lista a mano de ~30) y más mercados por partido, sin
        # el coste ni la fragilidad de Playwright (el fallo constante de "Más"/"Resultado
        # sin empate"/"Par/Impar" en sesión nueva, ya documentado en el propio
        # providers/cuotasahora.py, y ~30 s de navegador por partido vs. ~2.5 s de httpx
        # plano) - por eso un ciclo `full` con CuotasAhora tardaba horas. Único hueco real
        # de cobertura al quitarlo: beisbol_mlb y balonmano_champions (EHF), que
        # CasasDeApuestasProvider no tiene cableados todavía - pendiente si se echan en
        # falta. `CuotasAhoraProvider` sigue implementado en providers/cuotasahora.py por
        # si hace falta reactivarlo, solo se quita de aquí.
        # BetExplorerProvider retirado del ciclo lento 2026-09-28 (medido en la VM: 150 s de
        # sus 2 competiciones - LaLiga y Champions, por Playwright - de un ciclo de 14 min
        # 30 s, ~17 % del tiempo). CasasDeApuestasProvider (abajo) ya cubre esas mismas 2
        # competiciones, con TODAS las mismas casas de su ALLOWED_BOOKMAKERS (comprobado
        # contra su lista: 1xbet, 888sport, bet365, betway, bwin, codere, luckia, paf,
        # retabet, speedybet, versus, williamhill - las 12 presentes en la caché real de
        # casasdeapuestas), más otras ~13 casas y sin navegador. Ese tiempo libre lo usa
        # el ciclo lento para refrescar más competiciones de CasasDeApuestasProvider, la
        # misma lógica que ya se aplicó a CuotasAhoraProvider. `BetExplorerProvider` sigue
        # implementado en providers/betexplorer.py por si hace falta reactivarlo.
        # Tercer comparador (verificado en vivo 2026-09-27): HTML plano sin navegador,
        # descubre TODAS las competiciones de cada deporte solo (no hace falta lista a
        # mano) y trae casas que ningún otro proveedor de aquí cubre en directo (bet365,
        # Codere, William Hill, Retabet, Kirolbet, Marca Apuestas, Casino Barcelona) más
        # dos deportes nuevos (hockey hielo, tenis de mesa) - ver
        # providers/casasdeapuestas.py.
        CasasDeApuestasProvider(max_matches=max_matches),
    ]


# Las ligas nuevas de fútbol (top 5 europeas, Copa del Rey, LaLiga2...) solo
# están cubiertas por CuotasAhoraProvider (ver su docstring y README.md
# "Competiciones soportadas"): Sportium/Betfair/Winamax ignoran las claves
# para las que no tienen `competition_urls`. Baloncesto y tenis, en cambio, sí
# tienen fuente directa desde 2026-09-24 (Altenar/Kambi no filtran por
# competición: traen TODOS los partidos de esos deportes, así que cruzan aquí
# igual que si estuvieran en `competition_urls`).
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
    # Deportes nuevos (2026-09-27), solo cubiertos por CasasDeApuestasProvider: ver su
    # docstring para por qué no llevan sufijo de competición (descubre solas todas las
    # que haya, no hace falta una clave por liga como con CuotasAhora).
    "hockey",
    "tenismesa",
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

    result = await run_scan_cycle(
        providers,
        SPORTS,
        config.BANKROLL,
        config.MIN_MARGIN,
        config.DB_PATH,
        active_state,
        notify=lambda text: notify_opportunity(bot, text),
        logger=logger,
        confirm_cycles=config.CONFIRM_CYCLES,
        round_step=config.ROUND_STEP,
        warn_margin=config.WARN_MARGIN,
        max_margin=config.MAX_MARGIN,
        verify_margin=config.VERIFY_MARGIN,
        verify_cycles=config.VERIFY_CYCLES,
        max_concurrency=config.MAX_CONCURRENT_FETCHES,
        health=SourceHealth(config.SOURCE_HEALTH_PATH, config.SOURCE_PARK_AFTER) if config.SOURCE_PARK_AFTER else None,
        peers=PeerEvents(config.PEER_EVENTS_PATH),
    )

    # Estado de cada fuente en el panel/snapshot: una con 0 mercados, o vacía en
    # la caché, es señal de que algo va mal. De las cacheadas se añade su edad.
    sources = result["sources"]
    for provider in middle:
        if isinstance(provider, CachedProvider) and provider.name in sources:
            sources[provider.name]["cache"] = provider.summary

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(active_state, ensure_ascii=False, indent=2), encoding="utf-8")

    export_started = time.perf_counter()
    snapshot = export_snapshot(
        config.DB_PATH,
        settings={
            "mode": mode,
            "phases": result.get("phases", {}),
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
    logger.info("Volcado del panel (snapshot + docs/data.json): %.1fs", time.perf_counter() - export_started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=("full", "fast", "slow"), default="full")
    args = parser.parse_args()
    started = time.perf_counter()
    if args.mode == "slow":
        run_slow()
    else:
        asyncio.run(run_scan(args.mode))
    logger.info("Tiempo total del proceso (modo %s): %.1fs", args.mode, time.perf_counter() - started)


if __name__ == "__main__":
    main()
