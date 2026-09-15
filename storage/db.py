import json
import sqlite3
from datetime import datetime, timedelta, timezone

from engine.models import SurebetOpportunity

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


def init_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(SCHEMA)


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
