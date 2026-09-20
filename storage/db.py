import json
import sqlite3
from datetime import datetime, timedelta, timezone

from engine.models import MarketComparison, SurebetOpportunity
from engine.quality import BLOCKING_FLAGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    event TEXT NOT NULL,
    sport TEXT NOT NULL,
    market_type TEXT NOT NULL,
    bookmakers TEXT NOT NULL,
    margin REAL NOT NULL,
    total_stake REAL NOT NULL,
    guaranteed_profit REAL NOT NULL,
    stakes_json TEXT NOT NULL,
    executed INTEGER NOT NULL DEFAULT 0
)
"""

# Estado actual de *toda* comparación de cuotas hecha en el último ciclo de
# escaneo, sea o no una surebet (a diferencia de `opportunities`, que solo
# guarda las que sí lo son). Es una foto del momento, no un histórico: cada
# fila se actualiza (UPSERT) en vez de acumularse, y las que dejan de
# aparecer en un ciclo se borran (ver storage.db.save_comparisons). Así el
# panel web puede mostrar "cómo está todo ahora mismo" sin que la tabla (y
# el .db commiteado al repo) crezca sin límite.
COMPARISONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS comparisons (
    key TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    sport TEXT NOT NULL,
    market_type TEXT NOT NULL,
    bookmakers TEXT NOT NULL,
    margin REAL NOT NULL,
    is_surebet INTEGER NOT NULL,
    odds_json TEXT NOT NULL,
    guaranteed_profit REAL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
)
"""


# Columnas añadidas a `comparisons` después de crear la primera versión de la
# tabla. `CREATE TABLE IF NOT EXISTS` no las añade a una base de datos que ya
# existe (surebets.db se commitea al repo y ya tiene datos), así que init_db las
# añade con ALTER TABLE si faltan.
COMPARISONS_EXTRA_COLUMNS = {
    "start_time": "TEXT",
    "flags_json": "TEXT",
    "reliability": "TEXT",
    "rounded_stakes_json": "TEXT",
    "rounded_profit": "REAL",
    # Desde cuándo es surebet de forma continua (la "edad" del arb); NULL si
    # ahora mismo no lo es.
    "surebet_since": "TEXT",
    # "verificada" / "pendiente" solo para márgenes muy altos (ver engine/scan.py)
    "verification": "TEXT",
}


def init_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(SCHEMA)
        conn.execute(COMPARISONS_SCHEMA)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(comparisons)")}
        for column, kind in COMPARISONS_EXTRA_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE comparisons ADD COLUMN {column} {kind}")


def save_opportunity(path: str, opp: SurebetOpportunity) -> int:
    bookmakers = ",".join(sorted({o.bookmaker for o in opp.market.outcomes}))
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO opportunities
               (detected_at, event, sport, market_type, bookmakers, margin,
                total_stake, guaranteed_profit, stakes_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opp.detected_at.isoformat(),
                opp.market.event,
                opp.market.sport,
                opp.market.market_type,
                bookmakers,
                opp.margin,
                opp.total_stake,
                opp.guaranteed_profit,
                json.dumps(opp.stakes),
            ),
        )
        return cur.lastrowid


def get_opportunities_since(path: str, since: datetime) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM opportunities WHERE detected_at >= ? ORDER BY detected_at DESC",
            (since.isoformat(),),
        ).fetchall()


def get_stats(path: str, days: int = 7) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = get_opportunities_since(path, since)
    total_profit = sum(r["guaranteed_profit"] for r in rows)
    return {
        "period_days": days,
        "count": len(rows),
        "total_potential_profit": round(total_profit, 2),
        "avg_margin": round(sum(r["margin"] for r in rows) / len(rows), 4) if rows else 0.0,
    }


def comparison_key(comparison: MarketComparison) -> str:
    market = comparison.market
    return "||".join((market.event, market.sport, market.market_type))


def save_comparisons(path: str, comparisons: list[MarketComparison]) -> None:
    """Reemplaza la foto actual de `comparisons` por el resultado de este
    ciclo: hace UPSERT de cada mercado comparado y borra los que ya no
    aparecieron (partido terminado, proveedor caído, etc.).
    """
    now = datetime.now(timezone.utc).isoformat()
    keys = [comparison_key(c) for c in comparisons]
    with sqlite3.connect(path) as conn:
        for comparison, key in zip(comparisons, keys):
            market = comparison.market
            bookmakers = ",".join(sorted({o.bookmaker for o in market.outcomes}))
            odds = [
                {
                    "name": o.name,
                    "bookmaker": o.bookmaker,
                    "odds": o.odds,
                    "source": o.source,
                    "fetched_at": o.fetched_at.isoformat() if o.fetched_at else None,
                }
                for o in market.outcomes
            ]
            existing = conn.execute(
                "SELECT first_seen_at, is_surebet, surebet_since FROM comparisons WHERE key = ?",
                (key,),
            ).fetchone()
            first_seen_at = existing[0] if existing else now
            if not comparison.is_surebet:
                surebet_since = None
            elif existing and existing[1] and existing[2]:
                surebet_since = existing[2]  # sigue siéndolo: conserva la edad
            else:
                surebet_since = now
            conn.execute(
                """INSERT INTO comparisons
                       (key, event, sport, market_type, bookmakers, margin, is_surebet,
                        odds_json, guaranteed_profit, first_seen_at, last_seen_at,
                        start_time, flags_json, reliability, rounded_stakes_json,
                        rounded_profit, surebet_since, verification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       bookmakers = excluded.bookmakers,
                       margin = excluded.margin,
                       is_surebet = excluded.is_surebet,
                       odds_json = excluded.odds_json,
                       guaranteed_profit = excluded.guaranteed_profit,
                       last_seen_at = excluded.last_seen_at,
                       start_time = excluded.start_time,
                       flags_json = excluded.flags_json,
                       reliability = excluded.reliability,
                       rounded_stakes_json = excluded.rounded_stakes_json,
                       rounded_profit = excluded.rounded_profit,
                       surebet_since = excluded.surebet_since,
                       verification = excluded.verification""",
                (
                    key,
                    market.event,
                    market.sport,
                    market.market_type,
                    bookmakers,
                    comparison.margin,
                    int(comparison.is_surebet),
                    json.dumps(odds, ensure_ascii=False),
                    comparison.guaranteed_profit,
                    first_seen_at,
                    now,
                    market.start_time.isoformat() if market.start_time else None,
                    json.dumps(comparison.flags),
                    comparison.reliability or None,
                    json.dumps(comparison.rounded_stakes) if comparison.rounded_stakes else None,
                    comparison.rounded_profit,
                    surebet_since,
                    comparison.verification or None,
                ),
            )
        if keys:
            placeholders = ",".join("?" for _ in keys)
            conn.execute(f"DELETE FROM comparisons WHERE key NOT IN ({placeholders})", keys)
        else:
            conn.execute("DELETE FROM comparisons")


def _is_blocked(row: sqlite3.Row) -> bool:
    flags = json.loads(row["flags_json"]) if row["flags_json"] else []
    return any(f in BLOCKING_FLAGS for f in flags)


def get_all_comparisons(path: str) -> list[sqlite3.Row]:
    """Surebets válidas primero, luego el resto por margen descendente y al
    final las descartadas por error de datos (margen absurdo, mercado
    incompleto...), que no deben tapar las comparaciones reales.
    """
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM comparisons").fetchall()
    return sorted(rows, key=lambda r: (not r["is_surebet"], _is_blocked(r), -r["margin"]))


def export_snapshot(
    path: str,
    recent_opportunities_limit: int = 100,
    max_comparisons: int = 3000,
    settings: dict | None = None,
) -> dict:
    """Vuelca el estado actual (las `max_comparisons` comparaciones con mayor
    margen + histórico reciente de surebets detectadas + estadísticas) a un
    dict serializable en JSON, pensado para publicarse como docs/data.json y
    alimentar el panel web estático (GitHub Pages).

    El tope existe porque el proveedor de Altenar (providers/altenar.py)
    multiplica por >10 el número de mercados comparados por ciclo (~11.000
    con córners, tarjetas, hándicaps...) y volcarlos todos hincharía el
    data.json a varios MB. `get_all_comparisons` ya viene ordenado por margen
    descendente (las surebets y casi-surebets van primero), así que lo que se
    recorta es lo menos interesante. La base de datos sí guarda todo.
    """
    comparisons = [
        {
            "event": r["event"],
            "sport": r["sport"],
            "market_type": r["market_type"],
            "bookmakers": r["bookmakers"],
            "margin": r["margin"],
            "is_surebet": bool(r["is_surebet"]),
            "odds": json.loads(r["odds_json"]),
            "guaranteed_profit": r["guaranteed_profit"],
            "first_seen_at": r["first_seen_at"],
            "last_seen_at": r["last_seen_at"],
            "start_time": r["start_time"],
            "flags": json.loads(r["flags_json"]) if r["flags_json"] else [],
            "reliability": r["reliability"],
            "rounded_stakes": json.loads(r["rounded_stakes_json"]) if r["rounded_stakes_json"] else None,
            "rounded_profit": r["rounded_profit"],
            "surebet_since": r["surebet_since"],
            "verification": r["verification"],
        }
        for r in get_all_comparisons(path)[:max_comparisons]
    ]

    since = datetime.now(timezone.utc) - timedelta(days=7)
    opportunities = [
        {
            "detected_at": r["detected_at"],
            "event": r["event"],
            "sport": r["sport"],
            "market_type": r["market_type"],
            "bookmakers": r["bookmakers"],
            "margin": r["margin"],
            "total_stake": r["total_stake"],
            "guaranteed_profit": r["guaranteed_profit"],
        }
        for r in get_opportunities_since(path, since)[:recent_opportunities_limit]
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings or {},
        "stats": get_stats(path, days=7),
        "comparisons": comparisons,
        "recent_opportunities": opportunities,
    }
