"""Modo continuo (Fase 2 de la hoja de ruta, 2026-10-01): un solo proceso siempre encendido en
vez de un ciclo completo cada 12 min.

Antes, cada ciclo esperaba a la fuente más lenta (Altenar, ~300 s) para cruzar nada, y luego no
volvía a mirar hasta 12 min después: una surebet que aparecía justo tras un ciclo tardaba hasta
~18 min en avisarse, y las reales duran minutos. Ahora:

- Cada fuente es un **carril** (`Lane`) que se lee en bucle a su propio ritmo (`interval`, medido
  desde el inicio de una lectura: si tarda más que eso, la siguiente empieza enseguida) y guarda en
  memoria su última lectura.
- Un **detector** cruza la última lectura de todas las fuentes en cuanto alguna trae datos nuevos
  (como mucho cada `min_detect_interval`), con el mismo ciclo de siempre (`engine.scan`): las
  fuentes que ve son vistas en memoria (`LaneView`), que responden al instante.

Lo que cambia respecto al ciclo de un disparo, a propósito:
- El aparcado de fuentes (engine/health.py) y los avisos de fuente muerta (engine/alerts.py) se
  anotan por LECTURA de cada carril, no por análisis (el detector corre mucho más a menudo que las
  lecturas y contaría varias veces la misma).
- La segunda pasada de PokerStars usa las lecturas en memoria de las demás casas.
- Las surebets de margen muy alto sin verificar exigen un tiempo mínimo (`verify_min_age`) en vez
  de N análisis seguidos.
- Una lectura más vieja que `max_age` deja de usarse (fuente caída = no cruza con datos viejos).
"""

import asyncio
import ctypes
import gc
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from providers.base import OddsProvider

from .alerts import SourceAlerts
from .health import SourceHealth
from .models import Market
from .peers import PeerEvents
from .scan import _fetch, _refine

logger = logging.getLogger(__name__)


@dataclass
class Lane:
    """Una fuente y su última lectura buena."""

    provider: OddsProvider
    interval: timedelta
    max_age: timedelta
    markets: list[Market] = field(default_factory=list)
    read_at: datetime | None = None  # última lectura buena (con mercados)
    attempted_at: datetime | None = None
    ok: bool = False  # la última lectura no falló
    seconds: float = 0.0
    wait_seconds: float = 0.0
    reads: int = 0
    parked_until: datetime | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    def fresh(self, now: datetime) -> list[Market]:
        if self.read_at is None or now - self.read_at > self.max_age:
            return []
        return self.markets

    def status(self, now: datetime) -> dict:
        """Mismo formato que el `sources` de engine.scan (lo leen el panel y las alertas)."""
        fresh = self.fresh(now)
        info = {
            "ok": self.ok,
            "markets": len(fresh),
            "events": len({(m.sport, m.event) for m in fresh}),
            "seconds": round(self.seconds, 1),
            "wait_seconds": round(self.wait_seconds, 1),
            "age_seconds": round((now - self.read_at).total_seconds()) if self.read_at else None,
            "interval_seconds": round(self.interval.total_seconds()),
        }
        if self.parked_until and self.parked_until > now:
            info["parked"] = True
            info["retry_in_minutes"] = round((self.parked_until - now).total_seconds() / 60)
        return info


class LaneView(OddsProvider):
    """Lo que ve el detector de un carril: su última lectura, al instante. Nada de navegador ni
    de relecturas (la verificación de márgenes altos va por tiempo, ver `verify_min_age`)."""

    fast_recheck = False
    uses_browser = False
    refines = False
    parkable = False

    def __init__(self, lane: Lane, clock: Callable[[], datetime]):
        self.lane = lane
        self.name = lane.name
        self._clock = clock

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return list(self.lane.fresh(self._clock()))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def release_memory() -> None:
    """Devuelve al sistema la memoria que Python ya liberó. Medido en la VM el 2026-10-01: las
    cuotas en memoria ocupan ~200 MB, pero el proceso llegó a 2,5 GB (RAM + swap) en 30 min y agotó
    la swap: cada lectura grande (miles de fichas JSON en hilos) deja huecos que glibc no devuelve
    por sí solo. Con `malloc_trim` (y MALLOC_ARENA_MAX=2 en el servicio) sí."""
    gc.collect()
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


def memory_mb() -> float | None:
    """RAM + swap de este proceso en MB (Linux), o None donde no se puede saber."""
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            fields = dict(line.split(":", 1) for line in status if line.startswith(("VmRSS", "VmSwap")))
        return sum(int(value.split()[0]) for value in fields.values()) / 1024
    except (OSError, ValueError):
        return None


async def run_lane(
    lane: Lane,
    lanes: list[Lane],
    sports: list[str],
    updated: asyncio.Event,
    sem: asyncio.Semaphore | None,
    executor: ThreadPoolExecutor | None,
    health: SourceHealth | None = None,
    alerts: SourceAlerts | None = None,
    notify_admin: Callable[[str], Awaitable[None]] | None = None,
    peers: PeerEvents | None = None,
    clock: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_reads: int | None = None,
) -> None:
    """Lee `lane` en bucle para siempre (o `max_reads` veces, para los tests)."""
    provider = lane.provider
    while max_reads is None or lane.reads < max_reads:
        now = clock()
        wait = health.retry_in(provider.name, now) if health is not None and provider.parkable else None
        if wait is not None:
            lane.parked_until = now + wait
            await sleep(min(wait.total_seconds(), 600))
            continue
        lane.parked_until = None

        started = time.monotonic()
        timings: dict[str, dict] = {}
        fetched = await _fetch(provider, sports, logger, sem, timings, executor)
        if fetched is not None and provider.refines:
            others = [m for other in lanes if other is not lane and not other.provider.refines for m in other.fresh(clock())]
            if not others and peers is not None:
                others = peers.load(clock()) or []
            if others:
                fetched.extend(await _refine(provider, sports, others, logger, sem, timings, executor))
        lane.reads += 1
        lane.attempted_at = clock()
        lane.ok = fetched is not None
        lane.seconds = timings.get(provider.name, {}).get("run", 0.0)
        lane.wait_seconds = timings.get(provider.name, {}).get("wait", 0.0)
        if fetched:
            lane.markets = fetched
            lane.read_at = lane.attempted_at
            updated.set()
        logger.info(
            "Carril %s: %d mercados en %.1fs%s%s",
            provider.name,
            len(fetched or []),
            lane.seconds,
            f" (esperó turno {lane.wait_seconds:.1f}s)" if lane.wait_seconds >= 0.5 else "",
            "" if lane.ok else " (FALLÓ)",
        )
        fetched = None
        release_memory()

        if health is not None and provider.parkable:
            health.record(provider.name, good=bool(fetched), now=lane.attempted_at)
            try:
                health.save()
            except OSError:
                logger.warning("No se pudo guardar el estado de las fuentes aparcadas", exc_info=True)
        if alerts is not None and notify_admin is not None:
            text = alerts.update({provider.name: {"ok": lane.ok, "markets": len(fetched or [])}})
            if text:
                try:
                    await notify_admin(text)
                except Exception:
                    logger.warning("No se pudo enviar el aviso de fuentes", exc_info=True)

        if max_reads is not None and lane.reads >= max_reads:
            return
        await sleep(max(0.0, lane.interval.total_seconds() - (time.monotonic() - started)))


async def run_detector(
    lanes: list[Lane],
    updated: asyncio.Event,
    detect: Callable[[list[OddsProvider]], Awaitable[None]],
    min_interval: timedelta,
    clock: Callable[[], datetime] = utcnow,
    max_runs: int | None = None,
    startup_timeout: timedelta = timedelta(minutes=10),
    poll_seconds: float = 5.0,
) -> None:
    """Llama a `detect(vistas)` cada vez que algún carril trae datos nuevos, como mucho una vez
    cada `min_interval` (lo que llegue mientras tanto se junta en el siguiente análisis). Un fallo
    en un análisis se registra y no para el bucle.

    El PRIMER análisis espera a que todas las fuentes hayan intentado leer al menos una vez (o a
    `startup_timeout`): cruzar al arrancar solo con las rápidas "cerraría" las surebets activas de
    las lentas, y se volverían a avisar en cuanto llegaran."""
    views = [LaneView(lane, clock) for lane in lanes]
    deadline = time.monotonic() + startup_timeout.total_seconds()
    while time.monotonic() < deadline and not all(lane.reads or lane.parked_until for lane in lanes):
        await asyncio.sleep(poll_seconds)
    if time.monotonic() >= deadline:
        pending = [lane.name for lane in lanes if not (lane.reads or lane.parked_until)]
        if pending:
            logger.warning("Primer análisis sin esperar más a: %s", ", ".join(pending))
    runs = 0
    while max_runs is None or runs < max_runs:
        await updated.wait()
        updated.clear()
        started = time.monotonic()
        try:
            await detect(views)
        except Exception:
            logger.exception("Fallo en un análisis del modo continuo (se reintenta con los siguientes datos)")
        release_memory()
        runs += 1
        remaining = min_interval.total_seconds() - (time.monotonic() - started)
        if remaining > 0 and (max_runs is None or runs < max_runs):
            await asyncio.sleep(remaining)
