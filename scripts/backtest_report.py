"""Informe del backtest: qué pasó con las surebets detectadas (ver engine/backtest.py).

    python scripts/backtest_report.py                  # todo el histórico
    python scripts/backtest_report.py --days 7         # solo lo visto en los últimos 7 días
    python scripts/backtest_report.py --csv episodios.csv   # además vuelca cada episodio a CSV
    python scripts/backtest_report.py --db cache/backtest.db

Cómo leerlo: una surebet que desaparece porque la cuota SE MOVIÓ (`cuota_movida`) era real, no un
error de lectura; en una casa que mueve cuotas deprisa es lo normal. Los errores de lectura se ven
en las descartadas por el control de calidad y en las que tenían una pata de comparador.
"""

import argparse
import csv
import json
import os
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine.backtest import ODDS_EPSILON, _connect, leg_change_pct  # noqa: E402

REASON_TEXT = {
    "cuota_movida": "la cuota se movio (surebet real, no es error)",
    "relevo_de_casas": "sigue siendo surebet con otras casas",
    "pata_desaparecida": "la casa ya no ofrece ese resultado",
    "mercado_desaparecido": "el mercado ya no sale en ninguna fuente",
    "partido_empezado": "desaparecio con el partido ya empezado",
    "sin_datos": "la fuente no respondio (no concluyente)",
    "sin_cambio_visible": "mismas cuotas y ya no es surebet (raro, revisar)",
}
MARGIN_BUCKETS = ((0.0, 0.02, "1-2 %"), (0.02, 0.05, "2-5 %"), (0.05, 0.15, "5-15 %"), (0.15, 9.0, ">15 %"))


def load(path: str, days: int | None) -> list[sqlite3.Row]:
    if not os.path.exists(path):
        sys.exit(f"No existe {path}: el histórico se crea solo con el primer ciclo que lo tenga activado.")
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            return conn.execute("SELECT * FROM episodes WHERE last_seen >= ?", (since,)).fetchall()
        return conn.execute("SELECT * FROM episodes").fetchall()


def minutes(row) -> float:
    return (datetime.fromisoformat(row["last_seen"]) - datetime.fromisoformat(row["first_seen"])).total_seconds() / 60


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"


def median(values: list[float]) -> str:
    return f"{statistics.median(values):6.1f}" if values else "     -"


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def summary(rows: list[sqlite3.Row]) -> None:
    closed = [r for r in rows if r["status"] == "cerrada"]
    section("Resumen")
    print(f"Episodios: {len(rows)}  (abiertos ahora: {len(rows) - len(closed)}, cerrados: {len(closed)})")
    print(f"Avisadas por Telegram: {sum(r['notified'] for r in rows)}")
    print(f"Descartadas por el control de calidad (error de datos): {sum(r['discarded'] for r in rows)}")
    print(f"Con alguna pata de comparador: {sum(r['has_comparator_leg'] for r in rows)}")
    if rows:
        print(f"Desde {min(r['first_seen'] for r in rows)[:16]} hasta {max(r['last_seen'] for r in rows)[:16]} (UTC)")


def reasons(rows: list[sqlite3.Row]) -> None:
    closed = [r for r in rows if r["status"] == "cerrada"]
    section("Por que terminaron (episodios cerrados)")
    counts = Counter(r["end_reason"] for r in closed)
    for reason, n in counts.most_common():
        print(f"{n:6d} {pct(n, len(closed))}  {reason:<22} {REASON_TEXT.get(reason, '')}")


def lifetimes(rows: list[sqlite3.Row]) -> None:
    closed = [r for r in rows if r["status"] == "cerrada"]
    section("Cuanto duran (los cerrados)")
    print("Un episodio visto en un solo ciclo marca 0 min: la resolucion es la del intervalo entre ciclos.")
    print(f"{'':<34}{'n':>6}{'1 ciclo':>9}{'mediana min':>13}{'max min':>9}")
    groups = {
        "todos": closed,
        "avisadas": [r for r in closed if r["notified"]],
        "solo casas directas": [r for r in closed if not r["has_comparator_leg"] and not r["discarded"]],
        "con pata de comparador": [r for r in closed if r["has_comparator_leg"] and not r["discarded"]],
        "descartadas (error de datos)": [r for r in closed if r["discarded"]],
    }
    for name, group in groups.items():
        mins = [minutes(r) for r in group]
        print(
            f"{name:<34}{len(group):>6}{pct(sum(r['cycles'] == 1 for r in group), len(group)):>9}"
            f"{median(mins):>13}{max(mins, default=0):>9.0f}"
        )


def by_margin(rows: list[sqlite3.Row]) -> None:
    closed = [r for r in rows if r["status"] == "cerrada"]
    section("Por margen maximo alcanzado")
    print(f"{'margen':<10}{'n':>6}{'cuota movida':>14}{'descartadas':>13}{'1 ciclo':>9}{'mediana min':>13}")
    for low, high, label in MARGIN_BUCKETS:
        group = [r for r in closed if low <= r["margin_max"] < high]
        print(
            f"{label:<10}{len(group):>6}"
            f"{pct(sum(r['end_reason'] == 'cuota_movida' for r in group), len(group)):>14}"
            f"{pct(sum(r['discarded'] for r in group), len(group)):>13}"
            f"{pct(sum(r['cycles'] == 1 for r in group), len(group)):>9}"
            f"{median([minutes(r) for r in group]):>13}"
        )


def by_bookmaker(rows: list[sqlite3.Row]) -> None:
    """Por casa: en cuántos episodios fue pata y, de los cerrados, cuántas veces su cuota fue la que
    se movió y cuánto (mediana de la variación)."""
    stats: dict[str, dict] = defaultdict(lambda: {"legs": 0, "closed": 0, "moved": 0, "changes": [], "disc": 0, "flags": 0})
    for row in rows:
        for leg in json.loads(row["legs_json"]):
            entry = stats[leg["bookmaker"]]
            entry["legs"] += 1
            entry["disc"] += row["discarded"]
            if row["status"] != "cerrada":
                continue
            entry["closed"] += 1
            change = leg_change_pct(leg)
            if change is not None and abs(change) > ODDS_EPSILON * 100:
                entry["moved"] += 1
                entry["changes"].append(change)
    section("Por casa (como pata de una surebet)")
    print("'movio' = su cuota ya era otra al desaparecer la surebet; 'var. mediana' = cuanto cambio (%).")
    print(f"{'casa':<18}{'patas':>7}{'descartadas':>13}{'movio':>8}{'var. mediana':>14}")
    for name, entry in sorted(stats.items(), key=lambda item: -item[1]["legs"]):
        print(
            f"{name:<18}{entry['legs']:>7}{pct(entry['disc'], entry['legs']):>13}"
            f"{pct(entry['moved'], entry['closed']):>8}{median(entry['changes']):>13}%"
        )


def by_sport(rows: list[sqlite3.Row]) -> None:
    section("Por deporte")
    print(f"{'deporte':<24}{'n':>6}{'descartadas':>13}{'cuota movida':>14}")
    closed = {r["id"] for r in rows if r["status"] == "cerrada"}
    for sport, n in Counter(r["sport"] for r in rows).most_common():
        group = [r for r in rows if r["sport"] == sport]
        print(
            f"{sport:<24}{n:>6}{pct(sum(r['discarded'] for r in group), n):>13}"
            f"{pct(sum(r['end_reason'] == 'cuota_movida' for r in group), sum(r['id'] in closed for r in group)):>14}"
        )


def by_flag(rows: list[sqlite3.Row]) -> None:
    flags = Counter(flag for r in rows for flag in json.loads(r["flags_json"]))
    if not flags:
        return
    section("Avisos de calidad mas frecuentes")
    for flag, n in flags.most_common():
        print(f"{n:6d} {pct(n, len(rows))}  {flag}")


def export_csv(rows: list[sqlite3.Row], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            ["id", "evento", "deporte", "mercado", "casas", "primera_vez", "ultima_vez", "ciclos", "minutos",
             "estado", "motivo_fin", "margen_inicial", "margen_max", "margen_final", "descartada", "avisada",
             "pata_comparador", "fiabilidad", "avisos", "patas"]
        )
        for r in rows:
            legs = "; ".join(
                f"{leg['leg']}@{leg['odds_first']:g}->{leg['odds_last']:g}"
                + (f"->{leg['odds_end']:g}" if leg.get("odds_end") else "")
                for leg in json.loads(r["legs_json"])
            )
            writer.writerow(
                [r["id"], r["event"], r["sport"], r["market_type"], r["bookmakers"], r["first_seen"], r["last_seen"],
                 r["cycles"], f"{minutes(r):.1f}", r["status"], r["end_reason"] or "", f"{r['margin_first']:.4f}",
                 f"{r['margin_max']:.4f}", f"{r['margin_last']:.4f}", r["discarded"], r["notified"],
                 r["has_comparator_leg"], r["reliability"] or "", ",".join(json.loads(r["flags_json"])), legs]
            )
    print(f"\nCSV con {len(rows)} episodios: {path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=config.BACKTEST_DB_PATH or "cache/backtest.db")
    parser.add_argument("--days", type=int, help="solo episodios vistos en los últimos N días")
    parser.add_argument("--csv", help="volcar cada episodio a este CSV")
    args = parser.parse_args()

    rows = load(args.db, args.days)
    if not rows:
        print("Todavía no hay episodios guardados.")
        return
    summary(rows)
    reasons(rows)
    lifetimes(rows)
    by_margin(rows)
    by_bookmaker(rows)
    by_sport(rows)
    by_flag(rows)
    if args.csv:
        export_csv(rows, args.csv)


if __name__ == "__main__":
    main()
