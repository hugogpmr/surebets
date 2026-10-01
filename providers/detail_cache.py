"""Fichas de partido (todos sus mercados) ya leídas, para no releer en cada vuelta las de partidos
lejanos (Fase 2 de la hoja de ruta, 2026-10-01).

Altenar y Kambi piden una ficha por casa y partido: ~800 peticiones solo en fútbol para Altenar,
~300 s por lectura, la mayoría de partidos de dentro de 1-2 días cuyas cuotas apenas se mueven. En
el modo continuo (engine/live.py) el proveedor vive todo el día, así que puede recordar lo leído:

- partido en las próximas `NEAR` horas: la ficha se relee en cada vuelta (es donde se mueven las
  cuotas y donde están las surebets que dan tiempo a apostar);
- hasta `MID`: se relee si tiene más de `MID_REFRESH`;
- más lejos: si tiene más de `FAR_REFRESH`.

Una ficha que toca releer y falla (429, corte) se sigue usando si tiene menos de `FALLBACK_MAX_AGE`:
mejor una cuota de hace un rato que hacer desaparecer el partido y re-avisar sus surebets cuando
vuelva. En el ciclo de un solo disparo (scan_once_action) el proveedor nace en cada ciclo y la caché
empieza vacía: se comporta exactamente como antes.

Las cuotas guardadas conservan su `fetched_at` real, así que el control de calidad ve su edad
(`cuotas_desfasadas` en engine/quality.py si las patas se leyeron con > 10 min de diferencia).
"""

import threading
from datetime import datetime, timedelta

from engine.models import Market

NEAR = timedelta(hours=6)
MID = timedelta(hours=24)
MID_REFRESH = timedelta(minutes=20)
FAR_REFRESH = timedelta(minutes=45)
FALLBACK_MAX_AGE = timedelta(minutes=30)


class DetailCache:
    def __init__(self):
        self._entries: dict[tuple, tuple[datetime, list[Market]]] = {}
        self._lock = threading.Lock()

    def due(self, key: tuple, start: datetime | None, now: datetime) -> bool:
        """True si hay que (re)leer la ficha `key` de un partido que empieza a las `start`."""
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or start is None:
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
