"""William Hill por su API JSON pública (plataforma OpenBet, prefijo `OB_` en
todos los IDs), sin navegador ni cookies.

`checklist.md`/README ya diagnosticaban bien la causa ("Bloqueo de IP
explícito... 'Data Centre block'"), pero solo se había probado desde IPs de
datacenter/VPN (este sandbox de desarrollo incluido: la propia web devuelve el
texto "desactiva tu VPN o evita utilizar un Centro de Datos"). Verificado en
vivo el 2026-09-23 desde el PC de producción del usuario (IP residencial):
`sports.williamhill.es` carga sin bloqueo, y detrás hay una API JSON pública
que responde igual (mismo JSON byte a byte) con o sin cookies de sesión, y
**también responde 200 desde este mismo sandbox** (a diferencia de la propia
página web, que sí sigue bloqueada aquí) — o sea, el bloqueo de IP es solo de
la web, no de esta API en concreto.

Endpoint: `GET /data/ngs/matches-competitions/matches/es-es/OB_SP9` (`OB_SP9`
= fútbol). Parámetros:
- `day`: `"today"` o el código de día de la semana tal cual los da
  `availableDays` de la propia respuesta (`"mon"`..`"sun"`, más `"future"` para
  todo lo que quede más allá de la semana);
- `page`: pagina por competición, no por partido (`hasMore`/`page` en la
  respuesta indican si hay que pedir la siguiente);
- `marketType`: el nombre TAL CUAL de un grupo de mercado, ver más abajo.

**Ojo con `marketType`**: pedir `"Ganador del partido"` (el texto que se ve en
la propia web) NO da el 1X2 normal, da la promo "2 Up" de William Hill
(`marketGroupNameToken: "|90 Minutes - 2 Up - Spain|"`, paga como ganador si tu
equipo se pone 2 goles arriba) — mismo caso que "Resultado VA (+2)" en
`providers/bwin.py`, no es una cuota de mercado normal y no sirve para
arbitraje. El 1X2 de verdad vive bajo el grupo
`"Ganador del Partido - Cuotas mejoradas"` (nombre de la web, algo confuso: por
dentro es simplemente `marketGroupNameToken: "|Ganador del partido|"`),
confirmado en vivo contrastando cuotas reales (Azerbaiyán-Tayikistán: 1.78 /
3.40 / 4.20 aquí, muy cerca de bet365 el mismo partido).

**Ampliado 2026-09-25**: además del listado (barato, todos los partidos en una
sola llamada), cada partido tiene una ficha propia con TODOS sus mercados,
`GET /data/ngs/event/es-es/OB_SP9/events/<event_id>/[<colección>]` (sin
`marketType`, sin navegador, misma API pública) — encontrada inspeccionando el
tráfico de red al abrir un partido en `sports.williamhill.es` (ver
`read_network_requests` de la sesión: la web la llama al navegar al detalle).
Sin colección en la URL da la colección "Popular" (Doble oportunidad, Ambos
equipos marcarán, Más/Menos de goles con TODAS las líneas — partido, 1er y 2º
tiempo — y "Victoria sin empate" = DNB); con `Tiempos y Periodos` da además
"Apuestas al 1er Tiempo" (1X2_HT). Los mercados se identifican por
`marketGroupName` (estable, no cambia de un partido a otro) o, para Doble
oportunidad, por un prefijo fijo — nunca por índice ni por el texto completo,
que incluye una frase explicativa variable. La colección "Hándicaps" se probó
y se descartó: es hándicap europeo de 3 vías con marcador (empate posible,
líneas enteras) igual que el ya rechazado en Zebet/Versus/888sport — ninguna
otra fuente de este repo lo emite, así que no cruza. Cada ficha pesa
~200-500 KB (incluye goleadores, que no se usan), así que esta segunda pasada
solo se hace para los partidos dentro de `extra_markets_horizon_hours` (24 h
por defecto, más corto que el horizonte del 1X2 en sí) para no disparar el
coste de un escaneo que aquí cubre TODAS las ligas del mundo (337 partidos
reales en la ventana de 48 h por defecto, verificado en vivo) — a diferencia
de Sportium/Marca Apuestas/Versus, que solo leen una competición.
`fast_recheck` pasa a `False` (como bwin/Winamax) porque una relectura ya no
es barata.
"""

import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from engine.models import Market, Outcome
from providers.altenar import _fmt_line
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

API_URL = "https://sports.williamhill.es/data/ngs/matches-competitions/matches/es-es/OB_SP9"
EVENT_URL = "https://sports.williamhill.es/data/ngs/event/es-es/OB_SP9/events/{event_id}/"
SOURCE_VERSION = "ngs@2.81.3"
# Nombre de grupo (tal cual lo pide la API en `marketType`) del 1X2 real, no de
# la promo "2 Up" (ver docstring del módulo).
MARKET_GROUP = "Ganador del Partido - Cuotas mejoradas"
BOOKMAKER = "williamhill"

DEFAULT_HORIZON_HOURS = 48
DEFAULT_EXTRA_MARKETS_HORIZON_HOURS = 24
DEFAULT_EXTRA_MARKETS_CONCURRENCY = 6

# Colección de la ficha de partido (segundo segmento de EVENT_URL) que trae el
# 1X2 de la 1ª parte; el resto de mercados nuevos ya están en la colección por
# defecto ("Popular", sin segmento).
COLLECTION_TIEMPOS = "Tiempos y Periodos"

# `marketGroupName` exacto de cada mercado nuevo, verificado en vivo el
# 2026-09-25 (no cambia entre partidos ni ligas, a diferencia del texto
# mostrado en la web que a veces lleva una frase explicativa detrás).
MG_BTTS = "Ambos equipos marcarán"
MG_DNB = "Victoria sin empate (en caso de empate se anula la apuesta)"
MG_1X2_HT = "Apuestas al 1er Tiempo"
# Prefijo: el nombre completo incluye una frase explicativa variable
# ("Doble oportunidad (Predecir la combinación de 2 resultados posibles...)").
MG_DC_PREFIX = "Doble oportunidad"
# `marketGroupName` de los tres mercados de Más/Menos (partido/1ª/2ª parte)
# viene en inglés estable, a diferencia del `name` visible en español.
OU_GROUPS = {
    "Total Match Goals Over/Under Goals Static": "",
    "1st Half Over/Under Goals Static": "_HT",
    "2nd Half Over/Under Goals Static": "_2H",
}
_OU_SELECTION_RE = re.compile(r"^(Más|Menos) de (\d+(?:\.\d+)?)$")
_DC_LABELS = {frozenset({"1", "X"}): "1X", frozenset({"X", "2"}): "X2", frozenset({"1", "2"}): "12"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
}


def _decimal_odds(selection: dict) -> float | None:
    if selection.get("status") != "A" or not selection.get("active") or not selection.get("displayed"):
        return None
    num, den = selection.get("currentPriceNum"), selection.get("currentPriceDen")
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)) or den <= 0:
        return None
    value = num / den + 1
    return value if value > 1.0 else None


def _parse_event(event: dict, competition_name: str) -> Market | None:
    if event.get("isInPlay") or event.get("settled") or event.get("status") != "A":
        return None
    start_raw = event.get("startDateTime")
    if not start_raw:
        return None
    start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))

    market = next(
        (m for m in event.get("markets", []) if m.get("name") == "Ganador del partido" and m.get("status") == "A"),
        None,
    )
    if market is None:
        return None
    selections = market.get("selections", [])
    if len(selections) != 3:
        return None
    draw = next((s for s in selections if s.get("name") == "Empate"), None)
    others = sorted((s for s in selections if s is not draw), key=lambda s: s.get("order", 0))
    if draw is None or len(others) != 2:
        return None
    home, away = others
    home_odds, draw_odds, away_odds = _decimal_odds(home), _decimal_odds(draw), _decimal_odds(away)
    if home_odds is None or draw_odds is None or away_odds is None:
        return None

    home_name, away_name = home.get("name"), away.get("name")
    if not home_name or not away_name:
        return None
    if is_excluded([competition_name, home_name, away_name], exclude_esports_default(), exclude_womens_default()):
        return None

    outcomes = [
        Outcome(name="1", bookmaker=BOOKMAKER, odds=home_odds),
        Outcome(name="X", bookmaker=BOOKMAKER, odds=draw_odds),
        Outcome(name="2", bookmaker=BOOKMAKER, odds=away_odds),
    ]
    return Market(
        event=f"{home_name} vs. {away_name}",
        sport="futbol",
        market_type="1X2",
        outcomes=outcomes,
        start_time=start,
    )


def _all_markets(detail: dict) -> list[dict]:
    """Aplana `markets` (lista plana) y `groupedMarkets[*]['markets']` (los
    agrupados bajo una pestaña, p.ej. Más/Menos por partido/1ª/2ª parte) en una
    sola lista: los mercados nuevos aparecen indistintamente en uno u otro
    según la colección, verificado en vivo el 2026-09-25."""
    markets = list(detail.get("markets") or [])
    for group in detail.get("groupedMarkets") or []:
        markets.extend(group.get("markets") or [])
    return markets


def _two_way(raw: dict, event_name: str, market_type: str, labels: dict[str, str]) -> Market | None:
    """Mercado de 2 resultados fijos (p.ej. Ambos equipos marcarán: Sí/No)."""
    selections = raw.get("selections", [])
    if len(selections) != 2:
        return None
    pairs = []
    for selection in selections:
        label = labels.get(selection.get("name"))
        odds = _decimal_odds(selection)
        if label is None or odds is None:
            return None
        pairs.append((label, odds))
    if {label for label, _ in pairs} != set(labels.values()):
        return None
    return Market(
        event=event_name, sport="futbol", market_type=market_type,
        outcomes=[Outcome(name=label, bookmaker=BOOKMAKER, odds=odds) for label, odds in pairs],
    )


def _team_two_way(raw: dict, event_name: str, market_type: str, home_name: str, away_name: str) -> Market | None:
    """Mercado de 2 resultados por equipo, sin empate (p.ej. DNB: "Victoria sin
    empate", donde el empate ni siquiera es una selección, se anula la apuesta)."""
    selections = raw.get("selections", [])
    if len(selections) != 2:
        return None
    pairs = []
    for selection in selections:
        name = selection.get("name")
        label = "1" if name == home_name else "2" if name == away_name else None
        odds = _decimal_odds(selection)
        if label is None or odds is None:
            return None
        pairs.append((label, odds))
    if {label for label, _ in pairs} != {"1", "2"}:
        return None
    return Market(
        event=event_name, sport="futbol", market_type=market_type,
        outcomes=[Outcome(name=label, bookmaker=BOOKMAKER, odds=odds) for label, odds in pairs],
    )


def _three_way(raw: dict, event_name: str, market_type: str, home_name: str, away_name: str) -> Market | None:
    """Mercado de 3 resultados con empate identificado por nombre "Empate",
    igual que el 1X2 de `_parse_event` (p.ej. 1X2 del 1er tiempo)."""
    selections = raw.get("selections", [])
    if len(selections) != 3:
        return None
    pairs = []
    for selection in selections:
        name = selection.get("name")
        label = "1" if name == home_name else "2" if name == away_name else "X" if name == "Empate" else None
        odds = _decimal_odds(selection)
        if label is None or odds is None:
            return None
        pairs.append((label, odds))
    if {label for label, _ in pairs} != {"1", "X", "2"}:
        return None
    return Market(
        event=event_name, sport="futbol", market_type=market_type,
        outcomes=[Outcome(name=label, bookmaker=BOOKMAKER, odds=odds) for label, odds in pairs],
    )


def _double_chance(raw: dict, event_name: str, home_name: str, away_name: str) -> Market | None:
    """Doble oportunidad: cada selección es texto libre ("Equipo o Empate"),
    se sustituyen equipos/empate por 1/X/2 y se clasifica por el par resultante
    - mismo truco que ya usa `providers/bwin.py::parse_fixture`."""
    selections = raw.get("selections", [])
    if len(selections) != 3:
        return None
    pairs = []
    for selection in selections:
        text = (selection.get("name") or "").replace("Empate", "X")
        for name, tag in sorted(((home_name, "1"), (away_name, "2")), key=lambda x: -len(x[0])):
            text = text.replace(name, tag)
        parts = {t.strip().upper() for t in text.split(" o ")}
        label = _DC_LABELS.get(frozenset(parts))
        odds = _decimal_odds(selection)
        if label is None or odds is None:
            return None
        pairs.append((label, odds))
    if {label for label, _ in pairs} != {"1X", "X2", "12"}:
        return None
    return Market(
        event=event_name, sport="futbol", market_type="DC",
        outcomes=[Outcome(name=label, bookmaker=BOOKMAKER, odds=odds) for label, odds in pairs],
    )


def _over_under_lines(raw: dict, event_name: str, suffix: str) -> list[Market]:
    """Más/Menos con muchas líneas en una sola selección-lista ("Más de 2.5",
    "Menos de 1.5"...): se agrupan por línea y solo se emite la línea si tiene
    ambos lados con cuota, igual que `providers/bet777.py::_line_markets`."""
    by_line: dict[str, dict[str, float]] = {}
    for selection in raw.get("selections", []):
        match = _OU_SELECTION_RE.match(selection.get("name") or "")
        odds = _decimal_odds(selection)
        if not match or odds is None:
            continue
        side = "Over" if match.group(1) == "Más" else "Under"
        line = _fmt_line(float(match.group(2)))
        by_line.setdefault(line, {})[side] = odds
    markets = []
    for line, sides in by_line.items():
        if "Over" in sides and "Under" in sides:
            markets.append(Market(
                event=event_name, sport="futbol", market_type=f"OU{suffix}_{line}",
                outcomes=[
                    Outcome(name="Over", bookmaker=BOOKMAKER, odds=sides["Over"]),
                    Outcome(name="Under", bookmaker=BOOKMAKER, odds=sides["Under"]),
                ],
            ))
    return markets


def parse_extra_markets(detail: dict, event_name: str, home_name: str, away_name: str) -> list[Market]:
    """Convierte la ficha de un partido (`_all_markets`) en los mercados nuevos
    (DC, BTTS, DNB, 1X2_HT, OU con todas las líneas de partido/1ª/2ª parte).
    Se identifican por `marketGroupName`, ver constantes del módulo."""
    found: dict[str, Market] = {}
    for raw in _all_markets(detail):
        name = raw.get("marketGroupName") or raw.get("name") or ""
        parsed: list[Market] = []
        if name == MG_BTTS:
            market = _two_way(raw, event_name, "BTTS", {"Sí": "Yes", "No": "No"})
            parsed = [market] if market else []
        elif name == MG_DNB:
            market = _team_two_way(raw, event_name, "DNB", home_name, away_name)
            parsed = [market] if market else []
        elif name == MG_1X2_HT:
            market = _three_way(raw, event_name, "1X2_HT", home_name, away_name)
            parsed = [market] if market else []
        elif name.startswith(MG_DC_PREFIX):
            market = _double_chance(raw, event_name, home_name, away_name)
            parsed = [market] if market else []
        elif name in OU_GROUPS:
            parsed = _over_under_lines(raw, event_name, OU_GROUPS[name])
        for market in parsed:
            found.setdefault(market.market_type, market)
    return list(found.values())


class WilliamHillProvider(OddsProvider):
    """William Hill por su API JSON pública (ver docstring del módulo). Solo
    1X2 de fútbol dentro de `horizon_hours` (listado, una sola llamada barata)
    más DC/BTTS/DNB/1X2_HT/OU (partido, 1ª y 2ª parte, todas las líneas) leyendo
    la ficha de cada partido dentro de `extra_markets_horizon_hours`, más corto
    que `horizon_hours` porque esta casa cubre todas las ligas del mundo y cada
    ficha pesa varios cientos de KB (ver docstring del módulo). Sin navegador,
    pero ya no es lo bastante barato como para releerse en el mismo escaneo."""

    name = BOOKMAKER
    fast_recheck = False

    def __init__(
        self,
        horizon_hours: int = DEFAULT_HORIZON_HOURS,
        extra_markets_horizon_hours: int = DEFAULT_EXTRA_MARKETS_HORIZON_HOURS,
        extra_markets_concurrency: int = DEFAULT_EXTRA_MARKETS_CONCURRENCY,
    ):
        self.horizon_hours = horizon_hours
        self.extra_markets_horizon_hours = extra_markets_horizon_hours
        self.extra_markets_concurrency = extra_markets_concurrency

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        with httpx.Client(headers=HEADERS, timeout=30) as client:
            return self._fetch_football(client)

    def _fetch_day(self, client: httpx.Client, day: str) -> tuple[list[dict], list[dict]]:
        """(competiciones, availableDays) de todas las páginas de ese día."""
        competitions: list[dict] = []
        available_days: list[dict] = []
        page = 0
        while True:
            params = {
                "source": SOURCE_VERSION,
                "sortKey": "competition",
                "day": day,
                "marketType": MARKET_GROUP,
                "availableDays": "true",
                "page": page,
            }
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()
            competitions.extend(data.get("competitions", []))
            if page == 0:
                available_days = data.get("availableDays", [])
            if not data.get("hasMore"):
                break
            page += 1
        return competitions, available_days

    def _fetch_football(self, client: httpx.Client) -> list[Market]:
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)

        try:
            competitions, available_days = self._fetch_day(client, "today")
        except httpx.HTTPError:
            logger.warning("William Hill: fallo leyendo 'today'", exc_info=True)
            return []

        for entry in available_days:
            try:
                day_date = datetime.fromisoformat(str(entry["date"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if day_date > limit or entry.get("day") not in (
                "mon", "tue", "wed", "thu", "fri", "sat", "sun",
            ):
                continue
            try:
                more, _ = self._fetch_day(client, entry["day"])
            except httpx.HTTPError:
                logger.warning("William Hill: fallo leyendo el día '%s'", entry.get("day"), exc_info=True)
                continue
            competitions.extend(more)

        markets: list[Market] = []
        extra_events: list[tuple[str, str, str, str]] = []  # (event_id, event_name, home_name, away_name)
        extra_limit = now + timedelta(hours=self.extra_markets_horizon_hours)
        seen_events: set[str] = set()
        for competition in competitions:
            competition_name = competition.get("name") or ""
            for event in competition.get("events", []):
                event_id = event.get("id")
                if not event_id or event_id in seen_events:
                    continue
                seen_events.add(event_id)
                parsed = _parse_event(event, competition_name)
                if parsed is None or parsed.start_time is None or not (now < parsed.start_time <= limit):
                    continue
                markets.append(parsed)
                if parsed.start_time <= extra_limit:
                    home_name, away_name = parsed.event.split(" vs. ", 1)
                    extra_events.append((event_id, parsed.event, home_name, away_name))
        logger.info("William Hill: %d partidos 1X2 pre-partido en las próximas %d h", len(markets), self.horizon_hours)

        markets.extend(self._fetch_extra_markets(client, extra_events))
        return markets

    def _fetch_extra_markets(self, client: httpx.Client, events: list[tuple[str, str, str, str]]) -> list[Market]:
        """DC/BTTS/DNB/1X2_HT/OU de la ficha de cada partido en `events` (ver
        `parse_extra_markets`), en paralelo. Un fallo en un partido suelto no
        descarta el resto, igual que el resto de proveedores concurrentes de
        este repo (Altenar, bwin)."""
        if not events:
            return []

        def fetch(item: tuple[str, str, str, str]) -> list[Market]:
            event_id, event_name, home_name, away_name = item
            found: dict[str, dict] = {}
            for collection in (None, COLLECTION_TIEMPOS):
                try:
                    found[collection or ""] = self._fetch_event_detail(client, event_id, collection)
                except httpx.HTTPError:
                    logger.warning(
                        "William Hill: fallo leyendo ficha %s (%s)", event_id, collection or "Popular", exc_info=True
                    )
            markets: dict[str, Market] = {}
            for detail in found.values():
                for market in parse_extra_markets(detail, event_name, home_name, away_name):
                    markets.setdefault(market.market_type, market)
            return list(markets.values())

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.extra_markets_concurrency) as pool:
            for result in pool.map(fetch, events):
                markets.extend(result)
        logger.info("William Hill: %d mercados nuevos (DC/BTTS/DNB/1X2_HT/OU) en %d partidos", len(markets), len(events))
        return markets

    def _fetch_event_detail(self, client: httpx.Client, event_id: str, collection: str | None) -> dict:
        url = EVENT_URL.format(event_id=event_id)
        if collection:
            url += urllib.parse.quote(collection)
        response = client.get(url)
        response.raise_for_status()
        return response.json()
