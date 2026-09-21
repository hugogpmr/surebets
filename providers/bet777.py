"""Bet777.es por la API pública de su plataforma Sportify, sin navegador.

Bet777 (DIGITAL DISTRIBUTION MANAGEMENT IBÉRICA, S.A., en el registro de la DGOJ)
dejó SBTech en diciembre de 2023 y opera sobre una plataforma propia, Sportify,
con cuotas de FeedConstruct (SoftConstruct): una tercera fuente de precios distinta
de Altenar y Kambi, que es lo que más aporta al cruce entre plataformas. Su
frontend consume una API JSON pública sin autenticación (`bookmaker=bet777es`);
verificado en vivo el 2026-09-21:

- listado: `GET https://api.sportify.bet/echo/v1/events?sport=football&bookmaker=bet777es`
  -> `tree` -> competiciones -> eventos (`id`, `name`, `teams`, `starts_at` en UTC,
  `is_live`, `is_suspended`), con solo los mercados principales;
- detalle: `GET .../echo/v1/markets?event_id=<id>&bookmaker=bet777es&lang=en` ->
  ~214 mercados por partido (56 KB, ~0,3 s).

Los mercados se reconocen por `name_untranslated` (inglés, independiente del idioma
de la web) y los resultados por `kind`, y se emiten con los mismos prefijos de
`market_type` que Altenar, Kambi y los comparadores (`1X2`, `1X2_HT`, `DNB`, `BTTS`,
`OE`, `OU_<línea>`, `OU_HOME_<línea>`, `AH_<línea>`...) para que crucen. Cada mercado
de totales/hándicap trae todas sus líneas juntas (`Over (2.5)` / `Under (2.5)`); se
emparejan por línea y solo se emiten las parejas completas y sin suspender.

Limitaciones conocidas: NO tiene córners, tarjetas, tiros ni faltas (comprobado en
LaLiga y Premier: sus grupos son Popular, Goals, Asian Handicap, Goal Scorer, Halves y
Combination), así que compite sobre goles, hándicap asiático y mitades. Quedan fuera
(no son excluyentes y exhaustivos, o de jugador): doble oportunidad, marcador correcto,
bandas, combinadas, hándicap de 3 vías. La API no está documentada y puede cambiar.
"""

import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

API_BASE = "https://api.sportify.bet/echo/v1/"
BOOKMAKER_ID = "bet777es"
BOOKMAKER = "bet777"
# La web manda estas cabeceras; la API responde igual sin ellas, pero así el
# tráfico es el mismo que el de un navegador normal en bet777.es.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.bet777.es",
    "Referer": "https://www.bet777.es/",
}
# Ventana de partidos a leer (horas desde ahora): mismo criterio que Altenar y Kambi.
DEFAULT_HORIZON_HOURS = 48

# Tipos de mercado por la forma de sus resultados (`kind` de Bet777).
_THREE_WAY = "three_way"  # W1 / X / W2
_TWO_WAY = "two_way"  # Team1 / Team2 (empate no apuesta)
_YES_NO = "yes_no"
_ODD_EVEN = "odd_even"
_TOTAL = "total"  # Over (línea) / Under (línea), varias líneas en el mismo mercado
_HANDICAP = "handicap"  # Home (línea) / Away (línea), varias líneas

# Mercados de partido completo por `name_untranslated` -> (prefijo de market_type, tipo).
_FULL_TIME = {
    "Match Result": ("1X2", _THREE_WAY),
    "Draw No Bet": ("DNB", _TWO_WAY),
    "Both Teams To Score": ("BTTS", _YES_NO),
    "Total Goals Odd/Even": ("OE", _ODD_EVEN),
    "Total Goals": ("OU", _TOTAL),
    "Total Goals Asian": ("OU", _TOTAL),
    "Team 1 Total Goals": ("OU_HOME", _TOTAL),
    "Team 1 Total Goals Asian": ("OU_HOME", _TOTAL),
    "Team 2 Total Goals": ("OU_AWAY", _TOTAL),
    "Team 2 Total Goals Asian": ("OU_AWAY", _TOTAL),
    "Goals Handicap": ("AH", _HANDICAP),
    "Goals Asian Handicap": ("AH", _HANDICAP),
}
# Mismos mercados por mitad: el nombre empieza por "1st Half " / "2nd Half " y el
# resto va aquí (el resultado de la mitad se llama "Result", no "Match Result").
_HALF = {
    "Result": ("1X2", _THREE_WAY),
    "Draw No Bet": ("DNB", _TWO_WAY),
    "Both Teams To Score": ("BTTS", _YES_NO),
    "Total Goals Odd/Even": ("OE", _ODD_EVEN),
    "Total Goals": ("OU", _TOTAL),
    "Total Goals Asian": ("OU", _TOTAL),
    "Team 1 Total Goals": ("OU_HOME", _TOTAL),
    "Team 1 Total Goals Asian": ("OU_HOME", _TOTAL),
    "Team 2 Total Goals": ("OU_AWAY", _TOTAL),
    "Team 2 Total Goals Asian": ("OU_AWAY", _TOTAL),
    "Goals Handicap": ("AH", _HANDICAP),
    "Goals Asian Handicap": ("AH", _HANDICAP),
}
_HALF_RE = re.compile(r"^(1st|2nd) Half (.+)$")
_HALF_SUFFIX = {"1st": "_HT", "2nd": "_2H"}

_THREE_WAY_KINDS = {"W1": "1", "X": "X", "W2": "2"}
_TWO_WAY_KINDS = {"Team1": "1", "Team2": "2"}
_YES_NO_KINDS = {"Yes": "Yes", "No": "No"}
_ODD_EVEN_KINDS = {"Odd": "Odd", "Even": "Even"}
_LINE_RE = re.compile(r"\((-?\d+(?:\.\d+)?)\)\s*$")


def _fmt(value: float, signed: bool = False) -> str:
    text = str(int(value)) if value == int(value) else f"{value:g}"
    return "+" + text if signed and value > 0 else text


def _fmt_line(line: float, signed: bool = False) -> str:
    """Línea como string estable. Las de cuarto (x.25/x.75) se expresan como dos
    líneas ("2/2.5", "-0.5/-1", la más cercana a cero primero), igual que
    providers/altenar.py, providers/kambi.py y providers/betexplorer.py."""
    if (line * 4) % 2 == 1:
        first, second = sorted((line - 0.25, line + 0.25), key=abs)
        return f"{_fmt(first)}/{_fmt(second)}"
    return _fmt(line, signed=signed)


def _as_list(value) -> list:
    """La API serializa a veces una lista como objeto con claves "0", "1"... (visto
    en `markets` de algunos partidos, p.ej. de la liga argentina, 2026-09-21)."""
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else []


def _price(outcome: dict) -> float | None:
    """Cuota como la ve el usuario (2 decimales), o None si no se puede apostar."""
    if outcome.get("suspended") or outcome.get("visible") is False or outcome.get("status") is False:
        return None
    raw = (outcome.get("display_odds") or {}).get("decimal") or outcome.get("odds")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    value = math.floor(value * 100 + 0.5) / 100
    return value if value > 1.0 else None


def _outcome(name: str, market: dict, price: float) -> Outcome:
    can_cashout = market.get("can_cashout")
    return Outcome(
        name=name,
        bookmaker=BOOKMAKER,
        odds=price,
        cash_out=bool(can_cashout) if can_cashout is not None else None,
    )


def _classify(name: str) -> tuple[str, str] | None:
    """(prefijo de market_type con sufijo de mitad, tipo) de un mercado por su
    nombre en inglés, o None si no lo emitimos."""
    if name in _FULL_TIME:
        return _FULL_TIME[name]
    match = _HALF_RE.match(name)
    if match and match.group(2) in _HALF:
        prefix, kind = _HALF[match.group(2)]
        return prefix + _HALF_SUFFIX[match.group(1)], kind
    return None


def _fixed_market(event: str, sport: str, prefix: str, market: dict, labels: dict[str, str]) -> Market | None:
    if market.get("is_suspended"):
        return None
    by_label: dict[str, Outcome] = {}
    for raw in _as_list(market.get("outcomes")):
        label = labels.get(raw.get("kind"))
        price = _price(raw)
        if label is None or price is None or label in by_label:
            return None  # resultado desconocido, suspendido o repetido: mercado no fiable
        by_label[label] = _outcome(label, market, price)
    if set(by_label) != set(labels.values()):
        return None
    return Market(event=event, sport=sport, market_type=prefix, outcomes=[by_label[label] for label in labels.values()])


def _line_of(outcome: dict) -> float | None:
    match = _LINE_RE.search(outcome.get("name", ""))
    return float(match.group(1)) if match else None


def _line_markets(event: str, sport: str, prefix: str, kind: str, market: dict) -> list[Market]:
    """Mercados con varias líneas en uno: empareja los dos lados de cada línea."""
    if market.get("is_suspended"):
        return []
    sides = ("Over", "Under") if kind == _TOTAL else ("Home", "Away")
    by_line: dict[float, dict[str, tuple[float, dict]]] = {}
    for raw in _as_list(market.get("outcomes")):
        side = raw.get("kind")
        line = _line_of(raw)
        price = _price(raw)
        if side not in sides or line is None or price is None:
            continue
        # En hándicap la línea de cada lado va con su signo; ambos lados de una
        # misma línea se emparejan por la del local ("Away (2.5)" es "Home (-2.5)").
        key = line if (kind == _TOTAL or side == "Home") else -line
        by_line.setdefault(key, {})[side] = (price, raw)

    markets = []
    for line, found in sorted(by_line.items()):
        if set(found) != set(sides):
            continue
        if kind == _TOTAL:
            market_type = f"{prefix}_{_fmt_line(line)}"
            names = ("Over", "Under")
        else:
            market_type = f"{prefix}_{_fmt_line(line, signed=True)}"
            names = ("1", "2")
        markets.append(
            Market(
                event=event,
                sport=sport,
                market_type=market_type,
                outcomes=[_outcome(name, market, found[side][0]) for name, side in zip(names, sides)],
            )
        )
    return markets


def parse_event_markets(details: dict, event_name: str, sport: str = "futbol") -> list[Market]:
    """Convierte la respuesta de `/markets?event_id=...` (idioma `en`) en Markets."""
    markets: list[Market] = []
    for market in _as_list(details.get("markets")):
        if not isinstance(market, dict):
            continue
        spec = _classify(market.get("name_untranslated") or "")
        if spec is None:
            continue
        prefix, kind = spec
        if kind == _THREE_WAY:
            parsed = _fixed_market(event_name, sport, prefix, market, _THREE_WAY_KINDS)
        elif kind == _TWO_WAY:
            parsed = _fixed_market(event_name, sport, prefix, market, _TWO_WAY_KINDS)
        elif kind == _YES_NO:
            parsed = _fixed_market(event_name, sport, prefix, market, _YES_NO_KINDS)
        elif kind == _ODD_EVEN:
            parsed = _fixed_market(event_name, sport, prefix, market, _ODD_EVEN_KINDS)
        else:
            markets.extend(_line_markets(event_name, sport, prefix, kind, market))
            continue
        if parsed is not None:
            markets.append(parsed)
    return markets


class Bet777Provider(OddsProvider):
    """Bet777 por su API pública (plataforma Sportify, cuotas de FeedConstruct), solo
    fútbol pre-partido dentro de `horizon_hours`, sin fútbol virtual ni (por defecto)
    femenino (ver providers/filters.py). API barata y sin navegador, así que se puede
    releer en el mismo escaneo para verificar surebets de margen muy alto."""

    name = "bet777"
    fast_recheck = True

    def __init__(
        self,
        horizon_hours: int | None = None,
        max_workers: int = 3,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.horizon_hours = horizon_hours or int(os.environ.get("BET777_HORIZON_HOURS", DEFAULT_HORIZON_HOURS))
        self.max_workers = max_workers
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            return self._fetch_football(client)

    def _get_json(self, client, endpoint: str, **params) -> dict:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = client.get(API_BASE + endpoint, params={"bookmaker": BOOKMAKER_ID, **params})
            except httpx.TransportError as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code in (429, 502, 503, 504):
                last_error = RuntimeError(f"HTTP {response.status_code}")
                time.sleep(2.0 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"Bet777: red inestable o límite de peticiones en {endpoint}") from last_error

    def _list_events(self, client) -> list[dict]:
        data = self._get_json(client, "events", sport="football", lang="en")
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)
        events = []
        for tree_sport in data.get("tree", []):
            for competition in tree_sport.get("competitions", []):
                for event in competition.get("events", []):
                    if event.get("is_live") or event.get("is_suspended") or event.get("is_outright"):
                        continue
                    teams = event.get("teams") or []
                    if len(teams) != 2 or not event.get("starts_at"):
                        continue
                    # Nombre de competición/región y equipos: distinguen el fútbol
                    # virtual y el femenino, que no queremos.
                    labels = [competition.get("name"), event.get("competition_name"), event.get("region_name"), *teams]
                    if is_excluded(labels, self.exclude_esports, self.exclude_women):
                        continue
                    start = datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
                    if now < start <= limit:
                        events.append({"id": event["id"], "name": f"{teams[0].strip()} vs. {teams[1].strip()}", "start": start})
        return events

    def _fetch_football(self, client) -> list[Market]:
        events = self._list_events(client)
        logger.info("Bet777: %d partidos pre-partido en las próximas %d h", len(events), self.horizon_hours)

        def fetch(event):
            try:
                details = self._get_json(client, "markets", event_id=event["id"], lang="en")
            except Exception:
                logger.warning("Bet777: fallo en detalle %s", event["id"], exc_info=True)
                return []
            try:
                parsed = parse_event_markets(details, event["name"])
            except Exception:  # un partido con formato raro no debe tumbar a los demás
                logger.warning("Bet777: no se pudo interpretar %s", event["id"], exc_info=True)
                return []
            for market in parsed:
                market.start_time = event["start"]
            return parsed

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for result in pool.map(fetch, events):
                markets.extend(result)
        return markets
