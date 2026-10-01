"""Modo continuo (ver engine/live.py): sustituye al ciclo rápido de cada 12 min
(`scan_once_action.py --mode fast` + deploy/surebets-fast.timer) por un proceso siempre encendido
(deploy/surebets-live.service) que lee cada fuente a su ritmo y avisa en cuanto cruza una surebet.

    python scripts/run_live.py

Mismas fuentes, mismo motor, misma base de datos, mismo estado de avisos y mismo panel que el
ciclo rápido; el ciclo lento (comparador) sigue aparte y este proceso lee su caché. La subida a
GitHub del panel va en otro temporizador (deploy/vm_publish.sh), no en cada análisis.

Ritmo de cada fuente: `LIVE_INTERVALS` en config.py (segundos entre el inicio de dos lecturas).
"""

import asyncio
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from telegram import Bot  # noqa: E402

import config  # noqa: E402
from bot.telegram_bot import notify_admin, notify_opportunity  # noqa: E402
from engine.alerts import SourceAlerts  # noqa: E402
from engine.cache import CachedProvider, ComparatorCache  # noqa: E402
from engine.health import SourceHealth  # noqa: E402
from engine.live import Lane, memory_mb, run_detector, run_lane, utcnow  # noqa: E402
from engine.peers import PeerEvents  # noqa: E402
from engine.scan import _run_scan_cycle, normalize_state  # noqa: E402
from scripts.scan_once_action import (  # noqa: E402
    SNAPSHOT_PATH,
    SPORTS,
    STATE_PATH,
    comparator_providers,
    direct_providers,
    logger,
    open_backtest,
)
from storage.db import export_snapshot, init_db  # noqa: E402


def write_atomic(path: pathlib.Path, text: str) -> None:
    """Escribe en un temporal y lo renombra: el temporizador que sube el panel a GitHub nunca
    debe pillar un JSON a medio escribir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_lanes() -> list[Lane]:
    before, after = direct_providers()
    cache = ComparatorCache(config.COMPARATOR_CACHE_PATH)
    comparators = [
        CachedProvider(p.name, cache, timedelta(hours=config.COMPARATOR_MAX_AGE_HOURS)) for p in comparator_providers()
    ]
    lanes = []
    for provider in before + comparators + after:
        seconds = config.LIVE_INTERVALS.get(
            provider.name, config.LIVE_BROWSER_INTERVAL if provider.uses_browser else config.LIVE_DEFAULT_INTERVAL
        )
        interval = timedelta(seconds=seconds)
        # Una lectura sirve hasta 3 vueltas de su carril (mínimo 20 min): si la fuente falla una
        # vez no desaparecen sus surebets (y no se re-avisan al volver), pero si se cae del todo
        # deja de cruzar con datos viejos.
        lanes.append(Lane(provider, interval, max(3 * interval, timedelta(minutes=20))))
    return lanes


async def main() -> None:
    pathlib.Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.DB_PATH)
    lanes = build_lanes()
    bot = Bot(config.TELEGRAM_BOT_TOKEN)
    active_state: dict[str, dict] = {}
    if STATE_PATH.exists():
        active_state = normalize_state(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    backtest = open_backtest()
    peers = PeerEvents(config.PEER_EVENTS_PATH)
    health = SourceHealth(config.SOURCE_HEALTH_PATH, config.SOURCE_PARK_AFTER) if config.SOURCE_PARK_AFTER else None
    alerts = SourceAlerts(config.SOURCE_ALERTS_PATH, config.SOURCE_ALERT_AFTER, config.SOURCE_ALERT_IGNORE)
    # Un hilo por lectura y otro por segunda pasada de cada carril, más el análisis: más hilos solo
    # reparten la memoria en más zonas de glibc (ver engine.live.release_memory).
    executor = ThreadPoolExecutor(max_workers=2 * len(lanes) + 4, thread_name_prefix="carril")
    sem = asyncio.Semaphore(config.LIVE_MAX_BROWSERS) if config.LIVE_MAX_BROWSERS > 0 else None
    updated = asyncio.Event()
    last_export = 0.0

    async def admin(text: str) -> None:
        await notify_admin(bot, text)

    async def detect(views) -> None:
        nonlocal last_export
        result = await _run_scan_cycle(
            views,
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
            backtest=backtest,
            executor=executor,
            verify_min_age=timedelta(minutes=config.LIVE_VERIFY_MINUTES),
            log_sources=False,
        )
        write_atomic(STATE_PATH, json.dumps(active_state, ensure_ascii=False, indent=2))
        used = memory_mb()
        if used is not None and used > config.LIVE_MAX_MEMORY_MB:
            # Red de seguridad: antes de que la VM se quede sin memoria (y el kernel mate lo que
            # pille, navegadores incluidos), salir limpio; systemd lo reinicia en 30 s y el estado
            # de avisos ya está guardado arriba.
            logger.warning(
                "Memoria del modo continuo %.0f MB > %d MB: reinicio limpio", used, config.LIVE_MAX_MEMORY_MB
            )
            os._exit(0)
        if time.monotonic() - last_export < config.LIVE_EXPORT_SECONDS:
            return
        last_export = time.monotonic()
        now = utcnow()
        sources = {lane.name: lane.status(now) for lane in lanes}
        for lane in lanes:
            if isinstance(lane.provider, CachedProvider):
                sources[lane.name]["cache"] = lane.provider.summary
        snapshot = export_snapshot(
            config.DB_PATH,
            settings={
                "mode": "live",
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
        write_atomic(SNAPSHOT_PATH, json.dumps(snapshot, ensure_ascii=False, indent=2))
        try:  # para que PokerStars tenga con qué cruzar si el proceso se reinicia
            peers.save([m for lane in lanes if not lane.provider.refines for m in lane.fresh(now)], now)
        except OSError:
            logger.warning("No se pudo guardar los partidos para la segunda pasada", exc_info=True)

    logger.info(
        "Modo continuo (memoria al arrancar %s MB): %s",
        f"{memory_mb():.0f}" if memory_mb() is not None else "?",
        ", ".join(f"{lane.name} cada {lane.interval.total_seconds():.0f}s" for lane in lanes),
    )
    tasks = [
        asyncio.create_task(
            run_lane(lane, lanes, SPORTS, updated, sem, executor, health, alerts, admin, peers), name=lane.name
        )
        for lane in lanes
    ]
    tasks.append(
        asyncio.create_task(
            run_detector(
                lanes,
                updated,
                detect,
                timedelta(seconds=config.LIVE_MIN_DETECT_SECONDS),
                startup_timeout=timedelta(minutes=config.LIVE_STARTUP_MINUTES),
            ),
            name="detector",
        )
    )
    # Si una tarea muere (no debería: cada lectura y cada análisis capturan sus errores), se para
    # todo y systemd reinicia el servicio en vez de seguir cojo sin que nadie se entere.
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in done:
        if task.exception():
            raise task.exception()


if __name__ == "__main__":
    asyncio.run(main())
