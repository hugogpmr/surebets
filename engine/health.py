"""Salud de las fuentes que lanzan un navegador entero: "aparcar" las que llevan ciclos
seguidos fallando o vacías.

Medido en la VM el 2026-09-28 (2 vCPU, la IP de un datacenter): Sportium, Versus, Betfair y
bwin daban 0 mercados en 81-87 de 87 ciclos, pero cada ciclo lanzaba igualmente un Chromium
para cada una (20-45 s de espera hasta agotar el tiempo), quitándole CPU y RAM a las fuentes
que sí funcionan. Aparcada una fuente, se salta con una espera que se duplica en cada
reintento fallido (30 min, 1 h, 2 h, 4 h, 6 h como máximo), y una sola lectura buena la
"desaparca" del todo: si el bloqueo era temporal, se recupera sola.

El estado va en un JSON de `cache/` (fuera de git, ver .gitignore): es de CADA máquina. En git
lo compartirían la VM y el PC del usuario, y una fuente bloqueada en la VM quedaría aparcada
también en el PC, donde sí funciona.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_PATH = "cache/source_health.json"
BASE_RETRY = timedelta(minutes=30)
MAX_RETRY = timedelta(hours=6)


class SourceHealth:
    """`bad_streak`: lecturas seguidas fallidas o vacías. Con `park_after` o más, la fuente
    se salta hasta `last_attempt` + espera. `park_after` = 0 lo desactiva todo."""

    def __init__(self, path: str = DEFAULT_PATH, park_after: int = 5):
        self.path = path
        self.park_after = park_after
        self._entries: dict[str, dict] = {}
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for name, entry in raw.items():
                self._entries[name] = {
                    "bad_streak": int(entry["bad_streak"]),
                    "last_attempt": datetime.fromisoformat(entry["last_attempt"]),
                }
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            # Un fichero corrupto no debe tumbar el escaneo: se empieza de cero.
            logger.warning("No se pudo leer %s: se empieza sin historial de fuentes", path, exc_info=True)
            self._entries = {}

    def retry_in(self, name: str, now: datetime) -> timedelta | None:
        """Tiempo que falta para volver a intentar `name`, o None si toca leerla ahora."""
        entry = self._entries.get(name)
        if not self.park_after or entry is None or entry["bad_streak"] < self.park_after:
            return None
        delay = min(MAX_RETRY, BASE_RETRY * 2 ** (entry["bad_streak"] - self.park_after))
        remaining = entry["last_attempt"] + delay - now
        return remaining if remaining > timedelta(0) else None

    def streak(self, name: str) -> int:
        return self._entries.get(name, {}).get("bad_streak", 0)

    def record(self, name: str, good: bool, now: datetime) -> None:
        """Anota el resultado de una lectura real (las saltadas no se anotan)."""
        entry = self._entries.get(name)
        if good:
            if entry is not None:
                if entry["bad_streak"] >= self.park_after > 0:
                    logger.info("Fuente %s recuperada tras %d lecturas malas seguidas", name, entry["bad_streak"])
                del self._entries[name]
                self._dirty = True
            return
        streak = (entry["bad_streak"] if entry else 0) + 1
        self._entries[name] = {"bad_streak": streak, "last_attempt": now}
        self._dirty = True
        if self.park_after and streak == self.park_after:
            logger.warning(
                "Fuente %s aparcada tras %d lecturas malas seguidas: se reintenta cada vez más espaciada (30 min - 6 h)",
                name, streak,
            )

    def save(self) -> None:
        if not self._dirty:
            return
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            name: {"bad_streak": e["bad_streak"], "last_attempt": e["last_attempt"].astimezone(timezone.utc).isoformat()}
            for name, e in self._entries.items()
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        self._dirty = False
