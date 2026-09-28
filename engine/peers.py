"""Partidos que listaban las demás casas en el ciclo anterior, para que las fuentes con
segunda pasada (`OddsProvider.refines`, hoy PokerStars) no tengan que esperar a las más lentas.

Medido en la VM el 2026-09-28: la segunda pasada de PokerStars necesita saber qué partidos lista
otra casa, y esperaba a que TODAS las demás fuentes terminaran (la última, Altenar, tardó
3 min 40 s) para luego sumar ~60 s de navegador al final del ciclo. Los partidos que hay en la
cartelera casi no cambian de un ciclo al siguiente (12 min), así que basta con lo que vieron las
demás casas la última vez: la segunda pasada arranca nada más terminar el listado 1X2 y corre
mientras Altenar y Kambi siguen leyendo. Un partido que aparece por primera vez este ciclo
se queda sin mercados extra hasta el siguiente. Sin fichero (primer ciclo) o con datos muy
viejos, el escaneo vuelve a esperar a las demás fuentes, como antes.

El estado va en un JSON de `cache/` (fuera de git, propio de cada máquina).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .models import Market, Outcome

logger = logging.getLogger(__name__)

DEFAULT_PATH = "cache/peer_events.json"
# Más viejo que esto, ya no vale: la cartelera de partidos cambia.
MAX_AGE = timedelta(hours=6)
# Con menos partidos que esto el ciclo anterior salió cojo (p.ej. Altenar y Kambi caídos a la
# vez): mejor esperar a los datos frescos de este ciclo que decidir con casi nada.
MIN_EVENTS = 20


class PeerEvents:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    def _read(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (ValueError, OSError):
            logger.warning("No se pudo leer %s: se ignora", self.path, exc_info=True)
            return None

    def load(self, now: datetime) -> list[Market] | None:
        """Los partidos del ciclo anterior como mercados sintéticos (solo sirven para
        `engine.matching.peer_coverage`, nunca entran al cruce), o None si no hay datos
        válidos: sin fichero, corrupto, demasiado viejo o demasiado pobre."""
        raw = self._read()
        if not raw:
            return None
        try:
            saved_at = datetime.fromisoformat(raw["saved_at"])
            events = raw["events"]
            if now - saved_at > MAX_AGE or sum(len(by_event) for by_event in events.values()) < MIN_EVENTS:
                return None
            return [
                Market(
                    event=event,
                    sport=sport,
                    market_type="1X2",
                    outcomes=[Outcome(name="1", bookmaker=book, odds=2.0) for book in books],
                )
                for sport, by_event in events.items()
                for event, books in by_event.items()
            ]
        except (KeyError, ValueError, TypeError, AttributeError):
            logger.warning("Formato inesperado en %s: se ignora", self.path, exc_info=True)
            return None

    def age(self, now: datetime) -> timedelta | None:
        raw = self._read()
        try:
            return now - datetime.fromisoformat(raw["saved_at"]) if raw else None
        except (KeyError, ValueError, TypeError):
            return None

    def save(self, markets: list[Market], now: datetime) -> None:
        """Guarda qué casas listan cada partido de `markets` (los de las fuentes que NO tienen
        segunda pasada: no tiene sentido que PokerStars se cuente a sí misma)."""
        events: dict[str, dict[str, set[str]]] = {}
        for market in markets:
            books = events.setdefault(market.sport, {}).setdefault(market.event, set())
            books.update(o.bookmaker.lower() for o in market.outcomes)
        payload = {
            "saved_at": now.astimezone(timezone.utc).isoformat(),
            "events": {sport: {event: sorted(books) for event, books in by_event.items()} for sport, by_event in events.items()},
        }
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, self.path)  # atómico: un ciclo que muere a medias no deja el JSON cortado
