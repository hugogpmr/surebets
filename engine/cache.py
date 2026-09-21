"""Caché en disco de los mercados de los comparadores (CuotasAhora, BetExplorer).

Un ciclo completo de comparadores tarda horas (~30 s por partido, ~600 partidos
en las 38 competiciones): imposible dentro de un escaneo que tiene que avisar en
minutos. Por eso se separan en dos ritmos:

- ciclo LENTO (`scan_once_action.py --mode slow`): rota por (proveedor,
  competición), empezando por la que lleva más tiempo sin leerse, hasta agotar
  un presupuesto de tiempo, y guarda lo leído aquí;
- ciclo RÁPIDO (`--mode fast`, cada pocos minutos): lee solo las APIs directas
  (Altenar, Kambi, Sportium, Betfair, Winamax, ~1-2 min) y le suma esta caché
  mediante `CachedProvider`, que se comporta como un proveedor más.

Cada cuota conserva `source` y `fetched_at` originales, así que engine/quality.py
sigue viendo su antigüedad real (`cuotas_desfasadas`, `cerca_inicio`) aunque
venga de la caché. La caché está fuera de git (cache/, ver .gitignore): son
megas que cambian a cada ciclo lento.
"""

import dataclasses
import json
import os
import time
from datetime import datetime, timedelta, timezone

from providers.base import OddsProvider

from .models import Market, Outcome

DEFAULT_PATH = "cache/comparator_cache.json"
VERSION = 1

# Cada cuánto conviene releer una competición (horas), por prioridad. La
# prioridad es la posición de la clave en la lista de competiciones (LaLiga
# primero): las TOP_LEAGUES primeras son las que más cruzan con las APIs
# directas. Un dato pasa a no usarse a las COMPARATOR_MAX_AGE_HOURS (8), así que
# ningún intervalo debería superarlo.
TOP_LEAGUES = 6
TOP_INTERVAL = timedelta(hours=2)
FOOTBALL_INTERVAL = timedelta(hours=5)
OTHER_INTERVAL = timedelta(hours=8)
# Tras una lectura vacía: primer reintento a los 20 min, luego 40, 80... sin
# pasar del intervalo normal de esa competición.
RETRY_BASE = timedelta(minutes=20)
NEVER = datetime.min.replace(tzinfo=timezone.utc)


def _encode(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _dump_market(market: Market) -> dict:
    return {
        "event": market.event,
        "sport": market.sport,
        "market_type": market.market_type,
        "fetched_at": _encode(market.fetched_at),
        "start_time": _encode(market.start_time),
        "outcomes": [
            {f.name: _encode(getattr(o, f.name)) for f in dataclasses.fields(Outcome)} for o in market.outcomes
        ],
    }


def _parse_dt(value):
    return datetime.fromisoformat(value) if value else None


_OUTCOME_DATETIMES = {f.name for f in dataclasses.fields(Outcome) if "datetime" in str(f.type)}


def _load_market(raw: dict) -> Market:
    outcomes = []
    known = {f.name for f in dataclasses.fields(Outcome)}
    for o in raw["outcomes"]:
        data = {k: v for k, v in o.items() if k in known}  # tolera campos añadidos/retirados
        for name in _OUTCOME_DATETIMES & data.keys():
            data[name] = _parse_dt(data[name])
        outcomes.append(Outcome(**data))
    return Market(
        event=raw["event"],
        sport=raw["sport"],
        market_type=raw["market_type"],
        outcomes=outcomes,
        fetched_at=_parse_dt(raw["fetched_at"]) or datetime.now(timezone.utc),
        start_time=_parse_dt(raw.get("start_time")),
    )


def refresh_interval(key: str, rank: int) -> timedelta:
    """Intervalo objetivo de refresco de una competición según su prioridad
    (`rank` = posición de la clave en la lista de competiciones)."""
    if rank < TOP_LEAGUES:
        return TOP_INTERVAL
    return FOOTBALL_INTERVAL if key.split("_", 1)[0] == "futbol" else OTHER_INTERVAL


def retry_delay(empty_streak: int, interval: timedelta) -> timedelta:
    """Espera antes de reintentar tras `empty_streak` lecturas vacías seguidas."""
    return min(interval, RETRY_BASE * 2 ** max(empty_streak - 1, 0))


def supported_keys(provider: OddsProvider) -> list[str]:
    """Claves de competición que un proveedor sabe leer (las que tienen URL)."""
    return list(getattr(provider, "league_urls", {}) or {})


class ComparatorCache:
    """Entradas por (proveedor, clave de competición):
    {"saved_at": cuándo se guardaron los mercados, "attempted_at": último
    intento (aunque fallara), "empty_streak": lecturas vacías seguidas,
    "markets": [...]}.
    """

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    # -- E/S ---------------------------------------------------------------
    def _read(self) -> dict:
        for attempt in range(3):
            try:
                with open(self.path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if data.get("version") == VERSION:
                    return data
                break
            except FileNotFoundError:
                break
            except (json.JSONDecodeError, PermissionError, OSError):
                time.sleep(0.5 * (attempt + 1))  # el ciclo lento puede estar renombrando el fichero
        return {"version": VERSION, "entries": {}}

    def _write(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        for attempt in range(5):  # en Windows replace falla si otro proceso lo tiene abierto
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.5 * (attempt + 1))
        os.replace(tmp, self.path)

    # -- escritura (ciclo lento) ---------------------------------------------
    def update(self, provider: str, key: str, markets: list[Market], now: datetime | None = None) -> bool:
        """Guarda lo leído. Si la lectura vino VACÍA y ya había datos, conserva
        los antiguos (un 0 suele ser carga/limitación puntual del sitio, no que
        de repente no haya partidos) y solo anota el intento. Devuelve True si
        se sustituyeron los mercados."""
        now = now or datetime.now(timezone.utc)
        data = self._read()
        entry = data["entries"].setdefault(f"{provider}|{key}", {"saved_at": None, "attempted_at": None, "markets": []})
        entry["attempted_at"] = now.isoformat()
        entry["empty_streak"] = 0 if markets else entry.get("empty_streak", 0) + 1
        replaced = bool(markets) or not entry["markets"]
        if replaced:
            entry["markets"] = [_dump_market(m) for m in markets]
            entry["saved_at"] = now.isoformat()
        self._write(data)
        return replaced

    def stalest_first(self, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Ordena (proveedor, clave) por lo atrasadas que van respecto a su
        intervalo de refresco: primero las nunca leídas, luego las que llevan más
        tiempo pasadas de fecha. Tras una lectura vacía la fecha de reintento es
        la de `retry_delay`, no la del intervalo normal."""
        entries = self._read()["entries"]
        rank: dict[str, int] = {}
        for _, key in pairs:
            rank.setdefault(key, len(rank))

        def due(pair):
            entry = entries.get(f"{pair[0]}|{pair[1]}")
            if not entry or not entry.get("attempted_at"):
                return NEVER  # nunca leída: va antes que cualquier fecha
            interval = refresh_interval(pair[1], rank[pair[1]])
            wait = retry_delay(entry.get("empty_streak", 0), interval) if entry.get("empty_streak") else interval
            return datetime.fromisoformat(entry["attempted_at"]) + wait

        # A igualdad (p.ej. la primera vuelta, nada leído) manda el orden en que
        # se listaron las competiciones (el de prioridad: LaLiga primero) y se
        # intercalan los proveedores en vez de agotar uno antes de empezar el otro.
        return sorted(pairs, key=lambda pair: (due(pair), rank[pair[1]], pair[0]))

    # -- lectura (ciclo rápido) ----------------------------------------------
    def markets_for(
        self, provider: str, sports: list[str], max_age: timedelta, now: datetime | None = None
    ) -> tuple[list[Market], dict]:
        """Mercados cacheados de un proveedor para las competiciones pedidas y no
        más viejos que `max_age`, y un resumen (nº de competiciones, mercados, edad
        de la lectura más antigua/reciente)."""
        now = now or datetime.now(timezone.utc)
        markets: list[Market] = []
        ages = []
        wanted = set(sports)
        for name, entry in self._read()["entries"].items():
            prov, key = name.split("|", 1)
            if prov != provider or key not in wanted or not entry["saved_at"]:
                continue
            saved = datetime.fromisoformat(entry["saved_at"])
            if now - saved > max_age:
                continue
            markets.extend(_load_market(m) for m in entry["markets"])
            ages.append(now - saved)
        summary = {
            "leagues": len(ages),
            "markets": len(markets),
            "oldest_minutes": round(max(ages).total_seconds() / 60) if ages else None,
            "newest_minutes": round(min(ages).total_seconds() / 60) if ages else None,
        }
        return markets, summary


class CachedProvider(OddsProvider):
    """Se comporta como el proveedor original (mismo `name`, para que `Outcome.source`
    y las reglas de calidad lo traten como comparador) pero sirve lo guardado en la
    caché en vez de abrir un navegador."""

    fast_recheck = False

    def __init__(self, name: str, cache: ComparatorCache, max_age: timedelta):
        self.name = name
        self.cache = cache
        self.max_age = max_age
        self.summary: dict = {}

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        markets, self.summary = self.cache.markets_for(self.name, sports, self.max_age)
        return markets


def refresh_cache(
    providers: list[OddsProvider],
    sports: list[str],
    cache: ComparatorCache,
    budget: timedelta,
    logger,
    clock=time.monotonic,
) -> dict:
    """Ciclo lento: lee competiciones por orden de antigüedad hasta agotar el
    presupuesto de tiempo (se comprueba entre competiciones, así que una muy
    grande puede pasarse; la tarea programada no se solapa consigo misma).
    Devuelve {(proveedor, clave): nº de mercados leídos} de lo procesado."""
    pairs = [(p.name, key) for p in providers for key in supported_keys(p) if key in sports]
    by_name = {p.name: p for p in providers}
    deadline = clock() + budget.total_seconds()
    done: dict = {}
    for name, key in cache.stalest_first(pairs):
        if clock() >= deadline:
            logger.info("Presupuesto de tiempo agotado: quedan %d competiciones para el siguiente ciclo lento", len(pairs) - len(done))
            break
        started = clock()
        try:
            markets = by_name[name].fetch_markets([key])
        except Exception:
            logger.exception("Ciclo lento: fallo leyendo %s/%s", name, key)
            markets = []
        for market in markets:
            for outcome in market.outcomes:
                outcome.source = outcome.source or name
                outcome.fetched_at = outcome.fetched_at or market.fetched_at
        replaced = cache.update(name, key, markets)
        done[(name, key)] = len(markets)
        logger.info(
            "Ciclo lento: %s/%s -> %d mercados en %ds%s",
            name,
            key,
            len(markets),
            round(clock() - started),
            "" if replaced else " (lectura vacía: se conservan los datos anteriores)",
        )
    return done
