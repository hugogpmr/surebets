"""Fuentes de navegador que se leen cada varios ciclos en vez de en todos (2026-10-03).

Medido en la VM con el backtest (1-3 oct, ~3.000 surebets válidas): las lecturas directas de
Sportium, Marca Apuestas, Zebet y Versus no fueron ninguna pata de ninguna surebet (lo que aparece
de esas casas llega por el comparador), pero suman ~310 s de navegador por ciclo y son las que más
esperan turno (`MAX_CONCURRENT_FETCHES`). Leídas cada ~3 ciclos, el resto del ciclo se acorta.

En los ciclos sin lectura se sirve la última buena guardada en disco (el ciclo de un solo disparo
nace en cada vuelta, como `providers/detail_cache.py`), con su `fetched_at` real: si una de esas
cuotas forma pata con otras recién leídas, engine/quality.py la marca `cuotas_desfasadas` (más de
10 min) y la surebet baja a fiabilidad "baja", sin descartarse. Servirla es mejor que no tenerla:
sin lectura directa, la cuota de esa casa en el comparador (que puede ir más atrasada aún) pasaría
a contar, y las surebets con esa pata desaparecerían y volverían cada 3 ciclos.

Una lectura que falla o viene vacía no se guarda y no cuenta: el ciclo siguiente vuelve a leer, así
que el aparcado de engine/health.py ve las mismas lecturas malas seguidas que antes.
"""

import logging
import os
import pickle
from datetime import datetime, timedelta, timezone

from engine.models import Market
from providers.base import OddsProvider

logger = logging.getLogger(__name__)


class ThrottledProvider(OddsProvider):
    """Mismo `name` que `inner` (el panel, el aparcado y `Outcome.source` no notan la diferencia).
    Decide al crearse si toca leer en este ciclo: si no, `uses_browser` es False y no hace cola
    en el semáforo de navegadores."""

    def __init__(self, inner: OddsProvider, every: timedelta, path: str, now: datetime | None = None):
        self.inner = inner
        self.name = inner.name
        self.parkable = inner.parkable
        self.path = path
        self.now = now or datetime.now(timezone.utc)
        self.saved_at: datetime | None = None
        self.markets: list[Market] = []
        try:
            with open(path, "rb") as f:
                self.saved_at, self.markets = pickle.load(f)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("No se pudo leer %s: %s se lee en este ciclo", path, self.name, exc_info=True)
        self.due = self.saved_at is None or not self.markets or self.now - self.saved_at >= every
        self.uses_browser = inner.uses_browser if self.due else False

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not self.due:
            age = (self.now - self.saved_at).total_seconds() / 60
            logger.info("%s: sin leer en este ciclo, se usa la lectura de hace %.0f min", self.name, age)
            return self.markets
        markets = self.inner.fetch_markets(sports)
        if markets:
            # Antes de que engine/scan.py les ponga `source`: lo vuelve a poner al servirlas.
            tmp = f"{self.path}.tmp"
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(tmp, "wb") as f:
                    pickle.dump((self.now, markets), f)
                os.replace(tmp, self.path)
            except OSError:
                logger.warning("No se pudo guardar la lectura de %s", self.name, exc_info=True)
        return markets
