"""Histórico de surebets para el backtest (checklist_mejoras.md, punto 12).

Guarda cada surebet detectada como un *episodio*: desde el primer ciclo en que aparece hasta el
ciclo en que deja de aparecer, con la cuota de cada pata al empezar, al máximo/mínimo y al
terminar. Se registran TODAS las candidatas (también las que el control de calidad descarta por
error de datos, y las que aún no se han avisado), no solo las notificadas: para calibrar filtros
hace falta ver también lo que se descartó.

Lo que se quiere saber al cerrar un episodio es POR QUÉ terminó, porque una cuota que se mueve
rápido es lo normal y no es un error de lectura. Por eso el motivo sale de mirar, en el ciclo en
que desaparece, qué pasó con las mismas patas:

- `cuota_movida`: el mercado sigue y alguna pata tiene otra cuota. La surebet era real y se la
  llevó el mercado. NO es un error.
- `pata_desaparecida`: el mercado sigue pero la casa ya no ofrece ese resultado.
- `mercado_desaparecido`: el partido ya no aparece en ninguna fuente (suspendido, cerrado...).
- `partido_empezado`: desapareció con la hora de inicio ya pasada.
- `sin_datos`: la fuente de alguna pata no respondió varios ciclos seguidos. No concluyente: si la
  fuente falla un solo ciclo el episodio sigue abierto (`missed`) en vez de cerrarse y reabrirse.
- `relevo_de_casas`: el mercado sigue siendo surebet pero con otras casas (otra pata pasó a ser la
  mejor); el episodio de esas patas termina, la oportunidad no.
- `sin_cambio_visible`: todas las patas siguen con la misma cuota y aun así ya no es surebet.

Va en su propia base de datos (`cache/backtest.db`, fuera de git): el histórico crece con el
tiempo y no debe hinchar `data/surebets.db`.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from .quality import BLOCKING_FLAGS, COMPARATOR_SOURCES, DIRECT_SOURCES

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    event TEXT NOT NULL,
    sport TEXT NOT NULL,
    market_type TEXT NOT NULL,
    start_time TEXT,
    bookmakers TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    cycles INTEGER NOT NULL,
    missed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    end_reason TEXT,
    closed_at TEXT,
    margin_first REAL NOT NULL,
    margin_max REAL NOT NULL,
    margin_last REAL NOT NULL,
    discarded INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    has_comparator_leg INTEGER NOT NULL DEFAULT 0,
    reliability TEXT,
    flags_json TEXT NOT NULL,
    legs_json TEXT NOT NULL
)
"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_episodes_open ON episodes(status, key)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_first_seen ON episodes(first_seen)",
)

# Ciclos seguidos sin poder ver las fuentes de una pata antes de darlo por `sin_datos`.
MAX_MISSED_CYCLES = 3
# Variación de cuota (fracción) por debajo de la cual se considera la misma cuota: redondeos.
ODDS_EPSILON = 0.0005


def episode_key(comparison) -> str:
    """Misma clave que el dedupe de avisos (engine/scan.py:opportunity_key): el episodio es de unas
    patas concretas, no del mercado en general."""
    market = comparison.market
    bookmakers = ",".join(sorted({o.bookmaker for o in market.outcomes}))
    return "||".join((market.event, market.sport, market.market_type, bookmakers))


def market_key(market) -> str:
    return "||".join((market.event, market.sport, market.market_type))


def is_candidate(comparison, min_margin: float) -> bool:
    """Surebet válida, o surebet que el control de calidad tumbó por error de datos (ver
    engine/scan.py:_invalidate: deja `is_surebet` a False pero el margen sigue positivo)."""
    if comparison.is_surebet:
        return True
    return comparison.margin > min_margin and any(f in BLOCKING_FLAGS for f in comparison.flags)


def _leg_key(outcome) -> str:
    return f"{outcome.bookmaker}:{outcome.name}"


def _leg_reading(readings, bookmaker: str, name: str) -> float | None:
    """La cuota que tiene AHORA esa casa para ese resultado, con la misma regla que usa el motor
    para escoger (engine/matching.py:best_odds_per_outcome): manda la lectura directa de la casa
    sobre la de un comparador y, entre varias del mismo tipo, la más baja."""
    mine = [o for o in readings if o.bookmaker == bookmaker and o.name == name]
    if not mine:
        return None
    direct = [o for o in mine if o.source in DIRECT_SOURCES]
    return min(o.odds for o in (direct or mine))


def _changed(old: float, new: float) -> bool:
    return abs(new - old) / old > ODDS_EPSILON


def _is_comparator(source: str) -> bool:
    return source in COMPARATOR_SOURCES


def _dead_sources(sources: dict[str, dict]) -> set[str]:
    """Fuentes de las que este ciclo no se vio nada (caída, aparcada, vacía): si una pata viene de
    una de ellas, que la surebet no aparezca no dice nada sobre la cuota."""
    return {
        name for name, info in sources.items()
        if info.get("parked") or not info.get("ok") or not info.get("markets")
    }


@contextmanager
def _connect(path: str):
    """Como `with sqlite3.connect(...)`, pero además CIERRA la conexión (el `with` a secas solo
    confirma la transacción y deja el fichero abierto hasta que el recolector libere el objeto)."""
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class SurebetLog:
    _connect = staticmethod(_connect)

    def __init__(self, path: str, keep_days: int = 90):
        self.path = path
        self.keep_days = keep_days
        with self._connect(path) as conn:
            conn.execute(SCHEMA)
            for statement in INDEXES:
                conn.execute(statement)

    def record_cycle(
        self,
        comparisons: list,
        sources: dict[str, dict],
        now: datetime,
        min_margin: float,
        notified_keys: set[str] | None = None,
    ) -> dict[str, int]:
        """Anota un ciclo: abre episodios nuevos, actualiza los que siguen y cierra (con su motivo)
        los que ya no aparecen. `comparisons` son las del ciclo ya con sus flags. Devuelve un
        resumen {"abiertos", "actualizados", "cerrados"} para el log."""
        notified_keys = notified_keys or set()
        candidates = {episode_key(c): c for c in comparisons if is_candidate(c, min_margin)}
        by_market = {market_key(c.market): c for c in comparisons}
        still_open = {market_key(c.market) for c in candidates.values()}
        dead = _dead_sources(sources)
        summary = {"abiertos": 0, "actualizados": 0, "cerrados": 0}

        with self._connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            open_rows = {
                row["key"]: row
                for row in conn.execute("SELECT * FROM episodes WHERE status = 'abierta'")
            }

            for key, comparison in candidates.items():
                row = open_rows.get(key)
                if row is None:
                    self._insert(conn, key, comparison, now, key in notified_keys)
                    summary["abiertos"] += 1
                else:
                    self._update(conn, row, comparison, now, key in notified_keys)
                    summary["actualizados"] += 1

            for key, row in open_rows.items():
                if key in candidates:
                    continue
                market = row["key"].rsplit("||", 1)[0]
                if self._close(conn, row, by_market.get(market), market in still_open, dead, now):
                    summary["cerrados"] += 1

            if self.keep_days:
                cutoff = (now - timedelta(days=self.keep_days)).isoformat()
                conn.execute("DELETE FROM episodes WHERE status = 'cerrada' AND closed_at < ?", (cutoff,))
        return summary

    def _insert(self, conn, key: str, comparison, now: datetime, notified: bool) -> None:
        market = comparison.market
        legs = [
            {
                "leg": _leg_key(o),
                "bookmaker": o.bookmaker,
                "name": o.name,
                "source": o.source,
                "odds_first": o.odds,
                "odds_last": o.odds,
                "odds_min": o.odds,
                "odds_max": o.odds,
                "changed_at": o.odds_changed_at.isoformat() if o.odds_changed_at else None,
            }
            for o in market.outcomes
        ]
        discarded = not comparison.is_surebet
        conn.execute(
            """INSERT INTO episodes
                   (key, event, sport, market_type, start_time, bookmakers, first_seen, last_seen,
                    cycles, status, margin_first, margin_max, margin_last, discarded, notified,
                    has_comparator_leg, reliability, flags_json, legs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'abierta', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                market.event,
                market.sport,
                market.market_type,
                market.start_time.isoformat() if market.start_time else None,
                ",".join(sorted({o.bookmaker for o in market.outcomes})),
                now.isoformat(),
                now.isoformat(),
                comparison.margin,
                comparison.margin,
                comparison.margin,
                int(discarded),
                int(notified),
                int(any(_is_comparator(o.source) for o in market.outcomes)),
                comparison.reliability or None,
                json.dumps(sorted(comparison.flags)),
                json.dumps(legs, ensure_ascii=False),
            ),
        )

    def _update(self, conn, row, comparison, now: datetime, notified: bool) -> None:
        market = comparison.market
        legs = json.loads(row["legs_json"])
        current = {_leg_key(o): o for o in market.outcomes}
        for leg in legs:
            outcome = current.get(leg["leg"])
            if outcome is None:
                continue
            leg["odds_last"] = outcome.odds
            leg["odds_min"] = min(leg["odds_min"], outcome.odds)
            leg["odds_max"] = max(leg["odds_max"], outcome.odds)
            if outcome.odds_changed_at:
                leg["changed_at"] = outcome.odds_changed_at.isoformat()
        flags = sorted(set(json.loads(row["flags_json"])) | set(comparison.flags))
        conn.execute(
            """UPDATE episodes SET last_seen = ?, cycles = cycles + 1, missed = 0,
                   margin_max = MAX(margin_max, ?), margin_last = ?, discarded = ?,
                   notified = MAX(notified, ?), reliability = ?, flags_json = ?, legs_json = ?
               WHERE id = ?""",
            (
                now.isoformat(),
                comparison.margin,
                comparison.margin,
                int(not comparison.is_surebet),
                int(notified),
                comparison.reliability or None,
                json.dumps(flags),
                json.dumps(legs, ensure_ascii=False),
                row["id"],
            ),
        )

    def _close(self, conn, row, comparison, relay: bool, dead: set[str], now: datetime) -> bool:
        """Decide qué pasó con un episodio que ya no aparece. Devuelve True si lo cierra, False si
        lo deja abierto esperando a que vuelva la fuente que no se pudo ver."""
        legs = json.loads(row["legs_json"])
        start = datetime.fromisoformat(row["start_time"]) if row["start_time"] else None
        started = start is not None and start <= now
        unseen = {leg["source"] for leg in legs} & dead

        if comparison is None:
            if unseen and not started:
                reason = None if row["missed"] + 1 < MAX_MISSED_CYCLES else "sin_datos"
            else:
                reason = "partido_empezado" if started else "mercado_desaparecido"
        else:
            readings = getattr(comparison, "readings", None) or comparison.market.outcomes
            moved = vanished = 0
            for leg in legs:
                new = _leg_reading(readings, leg["bookmaker"], leg["name"])
                leg["odds_end"] = new
                if new is None:
                    # Sin lectura de esa casa: si su fuente no respondió, no sabemos nada de la pata.
                    if leg["source"] in dead:
                        continue
                    vanished += 1
                elif _changed(leg["odds_last"], new):
                    moved += 1
            if relay:
                reason = "relevo_de_casas"
            elif moved:
                reason = "cuota_movida"
            elif vanished:
                reason = "pata_desaparecida"
            elif unseen:
                reason = None if row["missed"] + 1 < MAX_MISSED_CYCLES else "sin_datos"
            else:
                reason = "sin_cambio_visible"

        if reason is None:
            conn.execute("UPDATE episodes SET missed = missed + 1 WHERE id = ?", (row["id"],))
            return False
        conn.execute(
            "UPDATE episodes SET status = 'cerrada', end_reason = ?, closed_at = ?, legs_json = ? WHERE id = ?",
            (reason, now.isoformat(), json.dumps(legs, ensure_ascii=False), row["id"]),
        )
        return True


def leg_change_pct(leg: dict) -> float | None:
    """Variación (%) de la cuota de una pata entre la última vez que fue surebet y la lectura al
    cerrar el episodio; negativa = bajó. None si no hay lectura final."""
    end = leg.get("odds_end")
    if end is None:
        return None
    return (end / leg["odds_last"] - 1) * 100
