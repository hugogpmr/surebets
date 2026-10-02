"""Fichas de partido (todos sus mercados) ya leídas, para no releer en cada vuelta las de partidos
lejanos (Fase 2 de la hoja de ruta, 2026-10-01).

Altenar y Kambi piden una ficha por casa y partido: ~9.000 peticiones por lectura en Altenar
(~460 s, la fuente más lenta del ciclo el 2-oct), la mayoría de partidos de dentro de 1-2 días cuyas
cuotas apenas se mueven. Así que se recuerda lo leído:

- partido en las próximas `NEAR` horas: la ficha se relee en cada vuelta (es donde se mueven las
  cuotas y donde están las surebets que dan tiempo a apostar);
- hasta `MID`: se relee si tiene más de `MID_REFRESH`;
- más lejos: si tiene más de `FAR_REFRESH`.

Una ficha que toca releer y falla (429, corte) se sigue usando si tiene menos de `FALLBACK_MAX_AGE`:
mejor una cuota de hace un rato que hacer desaparecer el partido y re-avisar sus surebets cuando
vuelva. En el modo continuo (engine/live.py) el proveedor vive todo el día y la caché va en memoria;
en el ciclo de un solo disparo (scan_once_action) el proveedor nace en cada ciclo, así que la caché
se guarda en disco (`DetailStore(path)`) y la carga el ciclo siguiente (2026-10-02).

Las cuotas guardadas conservan su `fetched_at` real, así que el control de calidad ve su edad
(`cuotas_desfasadas` en engine/quality.py si las patas se leyeron con > 10 min de diferencia).
"""

import logging
import os
import pathlib
import pickle
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from engine.models import Market

logger = logging.getLogger(__name__)

NEAR = timedelta(hours=6)
MID = timedelta(hours=24)
MID_REFRESH = timedelta(minutes=20)
FAR_REFRESH = timedelta(minutes=45)
FALLBACK_MAX_AGE = timedelta(minutes=30)
# Margen alrededor de la hora de inicio de una surebet a verificar: se releen todos los partidos que
# empiezan a esa hora, con holgura porque cada fuente da la hora a su manera (la ficha guardada
# no sirve para confirmar una cuota).
FORCE_WINDOW = timedelta(minutes=10)
# Cambia si cambia lo que se guarda: un fichero de otra versión se ignora.
_FORMAT = 1


class _Force:
    """Partidos que hay que releer aunque su ficha no haya caducado (verificación de margen alto):
    los que empiezan a alguna de `starts`, o todos si `everything`."""

    def __init__(self):
        self.starts: list[datetime] = []
        self.everything = False

    def __call__(self, start: datetime | None) -> bool:
        if self.everything:
            return True
        return start is not None and any(abs(start - s) <= FORCE_WINDOW for s in self.starts)


class DetailCache:
    def __init__(self, force: _Force | None = None):
        self._entries: dict[tuple, tuple[datetime, list[Market]]] = {}
        self._lock = threading.Lock()
        self._force = force

    def due(self, key: tuple, start: datetime | None, now: datetime) -> bool:
        """True si hay que (re)leer la ficha `key` de un partido que empieza a las `start`."""
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or start is None or (self._force is not None and self._force(start)):
            return True
        until_start = start - now
        if until_start <= NEAR:
            return True
        refresh = MID_REFRESH if until_start <= MID else FAR_REFRESH
        return now - entry[0] >= refresh

    def get(self, key: tuple, now: datetime, max_age: timedelta | None = None) -> list[Market] | None:
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or (max_age is not None and now - entry[0] > max_age):
            return None
        return entry[1]

    def put(self, key: tuple, markets: list[Market], now: datetime) -> None:
        with self._lock:
            self._entries[key] = (now, markets)

    def keep_only(self, keys: set[tuple]) -> None:
        """Olvida las fichas de partidos que ya no se listan (empezados, fuera del horizonte)."""
        with self._lock:
            for key in [k for k in self._entries if k not in keys]:
                del self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)


class DetailStore:
    """Una DetailCache por deporte del proveedor: cada lectura de un deporte olvida los partidos que
    ya no lista, y con una sola caché eso borraba las fichas de los demás deportes. Con `path` se
    carga de disco al crearse y `save()` la guarda (ciclo de un solo disparo)."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = pathlib.Path(path) if path else None
        self._force = _Force()
        self._sports: dict[str, DetailCache] = {}
        if self.path is not None:
            self._load()

    def for_sport(self, sport: str) -> DetailCache:
        if sport not in self._sports:
            self._sports[sport] = DetailCache(self._force)
        return self._sports[sport]

    @contextmanager
    def forcing(self, starts: list[datetime | None]):
        """Dentro del bloque se releen los partidos que empiezan a esas horas (todos, si alguna es
        None: sin hora no se puede acotar)."""
        self._force.everything = any(s is None for s in starts)
        self._force.starts = [s for s in starts if s is not None]
        try:
            yield
        finally:
            self._force.everything = False
            self._force.starts = []

    def save(self) -> None:
        if self.path is None:
            return
        began = time.monotonic()
        data = {"format": _FORMAT, "sports": {sport: dict(cache._entries) for sport, cache in self._sports.items()}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self.path)
        except OSError:
            logger.warning("No se pudo guardar la caché de fichas en %s", self.path, exc_info=True)
            return
        logger.info(
            "Caché de fichas guardada en %s: %d fichas, %.1f MB, %.1f s",
            self.path, len(self), self.path.stat().st_size / 1e6, time.monotonic() - began,
        )

    def _load(self) -> None:
        if not self.path.exists():
            return
        began = time.monotonic()
        try:
            with open(self.path, "rb") as fh:
                data = pickle.load(fh)
        except Exception:
            # fichero a medias o de otra versión del código: se empieza de cero (es solo una caché)
            logger.warning("Caché de fichas ilegible en %s: se ignora", self.path, exc_info=True)
            return
        if not isinstance(data, dict) or data.get("format") != _FORMAT:
            return
        for sport, entries in data["sports"].items():
            self.for_sport(sport)._entries.update(entries)
        logger.info("Caché de fichas cargada de %s: %d fichas, %.1f s", self.path, len(self), time.monotonic() - began)

    def __len__(self) -> int:
        return sum(len(cache) for cache in self._sports.values())


def plan(jobs, start_of, cache: DetailCache, now: datetime) -> tuple[list, list]:
    """(a leer, de la caché) para esta vuelta."""
    to_read, cached = [], []
    for job in jobs:
        (to_read if cache.due(job, start_of(job), now) else cached).append(job)
    return to_read, cached


def collect(jobs, to_read, results, cached, cache: DetailCache, now: datetime) -> tuple[list[Market], dict]:
    """Junta lo recién leído (`results`, en el orden de `to_read`; None = fallo) con lo guardado,
    actualiza la caché y olvida los partidos que ya no están en `jobs`."""
    markets: list[Market] = []
    failed = fallback = 0
    for job, result in zip(to_read, results):
        if result is None:
            failed += 1
            old = cache.get(job, now, FALLBACK_MAX_AGE)
            if old is not None:
                fallback += 1
                markets.extend(old)
            continue
        cache.put(job, result, now)
        markets.extend(result)
    for job in cached:
        markets.extend(cache.get(job, now) or [])
    cache.keep_only(set(jobs))
    return markets, {"leidas": len(to_read) - failed, "de_cache": len(cached), "fallos": failed, "respaldo": fallback}
