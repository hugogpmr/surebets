"""888sport (`providers/sport888.py`): API JSON propia (plataforma "Spectate" de
888 Holdings), leída desde una página ya cargada del navegador — mismo patrón que
`providers/bwin.py`.

**Verificado en vivo el 2026-09-24** con `chromium.launch(headless=True)` real: la
página de competición (`https://www.888sport.es/futbol/espana/la-liga/`) carga sin
Cloudflare/CAPTCHA y dispara ella misma, por `fetch()`, una llamada a
`POST https://spectate-web.888sport.es/spectate/sportsbook-req/getTournamentMatches/
football/spain/spanish-la-liga-primera` que devuelve el listado completo de
partidos ya estructurado en JSON (nada de DOM que parsear, a diferencia de
Sportium/Marca Apuestas/Zebet).

Esa llamada **suelta, sin sesión** (`curl`/`httpx` directo) da 403 — hay una
protección propia de 888 (dominios `safe-iplay.com`/`safe-installation.com` vistos
en el tráfico de red, no un WAF conocido como Cloudflare/Akamai) que exige las
cookies de sesión (`bbsess`, `spectate_session`, `anon_hash`) que la propia carga
completa de la página establece. Igual que bwin, la solución no es evasión: se
hace el mismo `fetch()` que hace el frontend, `credentials: 'include'`, **desde
dentro de la página ya cargada** en el navegador — verificado que una MISMA carga
de página sirve para pedir más de un torneo sin volver a navegar (reutilizando la
sesión), aunque de momento solo se pide LaLiga.

Estructura del listado (`getTournamentMatches`), verificada en vivo:

- `events`: dict `id -> evento`. Cada evento trae `event_status` ("PENDING" para
  pre-partido) e `inplay` (bool) — se descartan los que no sean exactamente
  pre-partido. `competitors`: dict de 2 competidores con `name` e `is_home_team`
  (identifica local/visitante sin ambigüedad, a diferencia de casas que solo dan
  el nombre en un orden esperado). `start_time`: ISO 8601 con timezone. `slug`
  ("barcelona-vs-getafe") + `id` identifican la ficha del partido (ver abajo).
  `markets`: dict `id -> mercado`; en esta llamada solo trae el mercado por
  defecto, `name == "Ganador del partido"` (1X2).

**Más mercados vía la ficha del partido (añadido 2026-09-24)**: cada evento tiene
una ficha propia con **79 mercados** en el partido comprobado, en
`GET .../spectate/sportsbook/getEventData/<deporte>/<país>/<torneo>/<slug>/<id>`
(misma protección de sesión que el listado — se pide igual, con un `fetch()`
DESDE la página ya cargada, en paralelo para todos los partidos de la
tourney con el mismo patrón `Promise.all` que `providers/bwin.py`, así que no
hace falta ni una navegación de página más). La respuesta trae
`event.markets.markets_selections` (dict `market_id -> selecciones`) donde cada
selección lleva un `market_name` en **inglés, estable** (no el nombre traducido
de `markets_details`, que si se usara), independiente del idioma de la web -
igual filosofía que `name_untranslated` en `providers/bet777.py`. Verificado en
vivo que el mismo `market_name` puede repetirse en dos formas de dato distintas:
- **Plana** (`Both Teams to Score`, `Draw No Bet`, `Double Chance`...): lista de
  selecciones con `type` (o, para Par/Impar, `selection_db_name` en inglés
  "Odd"/"Even" — su `type` viene `None`) y `decimal_price`.
- **Agrupada por línea** (`Total Goals Over/Under` y sus variantes de mitad/
  equipo): dict `{"<índice de línea>": {"<índice de lado>": <selección>}, ...,
  "grouped": true}` - se aplana antes de parear por `special_odds_value` (la
  línea), igual que `_line_markets` de `providers/bet777.py`.

Mercados añadidos, con los mismos prefijos que Altenar/Kambi/Winamax/bet777/
CuotasAhora para que crucen: `DC`/`DC_HT` ("Double Chance"/"Half-time Double
Chance", `type` "1/X"/"2/X"/"1/2" -> se traduce a "1X"/"X2"/"12"), `BTTS`/
`BTTS_HT`/`BTTS_2H`, `DNB`, `OE`/`OE_HT`/`OE_2H`, `OU`/`OU_HT`/`OU_2H`/`OU_HOME`/
`OU_AWAY` (todas las líneas disponibles). **Hándicap**: esta casa tiene, como
Zebet/Versus, dos mercados de "Handicap" distintos - el llano ("Handicap",
"Half-time Handicap", "2nd Half Handicap") es de 3 vías con empate y líneas
enteras, sin pareja en ninguna otra fuente de este repo, así que se descarta; el
único que se implementa es **"Handicap 2-Way"** (de momento solo visto para el
partido completo, no por mitad), 2 resultados con una única línea -> `AH`.

**Todas las ligas, más baloncesto y tenis (añadido 2026-09-29)**: en vez de un torneo
suelto, el listado por día
`POST .../spectate/sportsbook-req/getUpcomingEvents/<deporte>/<today|tomorrow>` (el mismo que
pinta la web en "Hoy"/"Mañana", verificado en vivo) trae TODOS los partidos pre-partido de un
deporte con sus slugs de categoría/torneo/partido (`category_slug`, `tournament_slug`, `slug`,
`id`), justo lo que hace falta para la URL de `getEventData`. Medido ese día desde headless:
147 partidos de fútbol (today+tomorrow), 230 de tenis y 35 de baloncesto; 60 fichas de fútbol
(19 MB de JSON, ~315 kB cada una) en 1,9 s con 5 peticiones a la vez. Para acotar la memoria de
la VM las fichas se piden y se interpretan de 40 en 40.

Vocabulario nuevo verificado en vivo ese día (mismo `market_name` inglés estable):

- Baloncesto: "Money Line" (`ML`), "Point Spread" (`AH`, varias líneas), "Total Points" (`OU`),
  "Odd or Even Total Points" (`OE`), "Will There Be Overtime?" (`OT`) y las variantes
  "1st Half ..."/"2nd Half ... (Inc. OT)"/"1st..4th Quarter ...". El "Money Line" de una mitad o
  cuarto NO se emite (es un ganador a dos vías cuyo trato del empate no consta): sí su "Draw No
  Bet" (`DNB_HT`, `DNB_Q1`...), como Altenar y Kambi.
- Tenis: "Which player will win the match?" (`ML`), "Set Winner (Set 1|2)" (`ML_SET1|2`), "Total"
  (juegos, `OU`) y "Game Handicap" (`AH`).

**Trampa de forma de datos nueva**: los mercados con varias líneas de hándicap llegan como
una LISTA de dicts `{"<línea>": [selecciones]}` (además de las formas plana y agrupada ya
conocidas); `_flatten_selections` ahora recorre cualquiera de las tres. Antes esos mercados se
leían como "sin nombre" y se perdían.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

LOBBY_URL = "https://www.888sport.es/futbol/espana/la-liga/"
API_BASE = "https://spectate-web.888sport.es/spectate/sportsbook-req/getTournamentMatches/"
EVENT_DATA_BASE = "https://spectate-web.888sport.es/spectate/sportsbook/getEventData/"
UPCOMING_BASE = "https://spectate-web.888sport.es/spectate/sportsbook-req/getUpcomingEvents/"

# Valor de `sport` de la API por cada clave interna nuestra que se lee con el listado por día.
API_SPORTS: dict[str, str] = {"futbol": "football", "baloncesto": "basketball", "tenis": "tennis"}
UPCOMING_DAYS = ("today", "tomorrow")
# Ventana de partidos (horas desde ahora): mismo criterio que Altenar, Kambi y Bet777.
DEFAULT_HORIZON_HOURS = 48
# Fichas de partido que se piden (y se interpretan) por tanda: acota la memoria, ver docstring.
EXTRAS_CHUNK = 40

# (deporte de la API, país, torneo) por cada clave interna nuestra que ya tenga
# tienda encontrada; ver docstring del módulo.
DEFAULT_TOURNAMENTS: dict[str, list[tuple[str, str, str]]] = {
    "futbol": [("football", "spain", "spanish-la-liga-primera")],
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

_MAIN_MARKET_NAME = "Ganador del partido"
_1X2_TYPES = ("1", "X", "2")

# fetch() DESDE la página ya cargada (credentials: 'include' reutiliza sus cookies
# de sesión): ver docstring del módulo, mismo patrón que providers/bwin.py.
_FETCH_JS = """async (url) => {
    const response = await fetch(url, {method: 'POST', credentials: 'include'});
    return response.ok ? await response.json() : null;
}"""

# Como _FETCH_MANY_JS de providers/bwin.py (varios fetch() concurrentes desde la misma página, uno
# por partido, reutilizando la sesión ya establecida), pero devuelve solo
# `event.markets.markets_selections` con la misma forma y, de cada selección (objeto con
# `decimal_price`), solo los campos que lee el parser. Medido en la VM el 2026-10-02: 40 fichas
# tardaban 1 s en descargarse y 19 s en pasar enteras del navegador a Python (~6 min por ciclo).
_FETCH_EXTRAS_JS = """async ({items, concurrency}) => {
    const KEEP = ['decimal_price', 'special_odds_value', 'active', 'betable', 'tradable', 'type',
                  'name', 'selection_db_name', 'market_name'];
    const prune = (node) => {
        if (Array.isArray(node)) return node.map(prune);
        if (node === null || typeof node !== 'object') return node;
        const out = {};
        if ('decimal_price' in node) {
            for (const key of KEEP) if (key in node) out[key] = node[key];
        } else {
            for (const key of Object.keys(node)) out[key] = prune(node[key]);
        }
        return out;
    };
    const out = {};
    let next = 0;
    async function worker() {
        while (next < items.length) {
            const item = items[next++];
            try {
                const response = await fetch(item.url, {credentials: 'include'});
                if (!response.ok) { out[item.id] = {error: response.status}; continue; }
                const data = await response.json();
                const selections = data && data.event && data.event.markets && data.event.markets.markets_selections;
                out[item.id] = data && data.event
                    ? {event: {markets: {markets_selections: prune(selections || {})}}}
                    : data;
            } catch (error) {
                out[item.id] = {error: String(error)};
            }
        }
    }
    await Promise.all(Array.from({length: concurrency}, worker));
    return out;
}"""

# (campo de la selección a usar como clave, {clave -> nombre de resultado}) por
# cada mercado de resultado fijo (sin línea). Ver docstring del módulo: Par/Impar
# no trae `type`, así que se lee `selection_db_name` (también en inglés).
_YES_NO_LABELS = ("type", {"Yes": "Yes", "No": "No"})
_DNB_LABELS = ("type", {"1": "1", "2": "2"})
_DC_LABELS = ("type", {"1/X": "1X", "2/X": "X2", "1/2": "12"})
_OE_LABELS = ("selection_db_name", {"Odd": "Odd", "Even": "Even"})

# `market_name` (inglés, de la propia selección) -> (market_type, (campo, mapa)).
_FIXED_MARKETS: dict[str, tuple[str, tuple[str, dict[str, str]]]] = {
    "Both Teams to Score": ("BTTS", _YES_NO_LABELS),
    "1st Half - Both Teams to Score": ("BTTS_HT", _YES_NO_LABELS),
    "Second Half Both Team To Score": ("BTTS_2H", _YES_NO_LABELS),
    "Draw No Bet": ("DNB", _DNB_LABELS),
    "Double Chance": ("DC", _DC_LABELS),
    "Half-time Double Chance": ("DC_HT", _DC_LABELS),
    "Odd or Even Total": ("OE", _OE_LABELS),
    "Half-time Odd or Even Total": ("OE_HT", _OE_LABELS),
    "2nd Half Odd or Even Total Goals": ("OE_2H", _OE_LABELS),
}
# `market_name` -> prefijo de market_type, para los mercados de línea (varias
# líneas agrupadas bajo el mismo market_id, ver docstring del módulo).
_TOTAL_MARKETS: dict[str, str] = {
    "Total Goals Over/Under": "OU",
    "Half-time Totals Over/Under": "OU_HT",
    "Second Half Totals Over / Under": "OU_2H",
    "Home Team Total Goals Over/Under": "OU_HOME",
    "Away Team Total Goals Over/Under": "OU_AWAY",
}
# Baloncesto y tenis (2026-09-29): mismas tres formas de tabla que el fútbol. Los resultados de
# un ganador a dos vías llevan `type` "1"/"2".
_TWO_WAY_LABELS = ("type", {"1": "1", "2": "2"})
_BASKETBALL_FIXED: dict[str, tuple[str, tuple[str, dict[str, str]]]] = {
    "Money Line": ("ML", _TWO_WAY_LABELS),
    "Odd or Even Total Points": ("OE", _OE_LABELS),
    "1st Half Odd or Even": ("OE_HT", _OE_LABELS),
    "2nd Half Odd or Even Total Points (Including Overtime)": ("OE_2H", _OE_LABELS),
    "Will There Be Overtime?": ("OT", _YES_NO_LABELS),
    "1st Half Draw No Bet": ("DNB_HT", _TWO_WAY_LABELS),
    "2nd Half Draw No Bet (Inc. OT)": ("DNB_2H", _TWO_WAY_LABELS),
    "1st Quarter Draw No Bet": ("DNB_Q1", _TWO_WAY_LABELS),
    "2nd Quarter Draw No Bet": ("DNB_Q2", _TWO_WAY_LABELS),
    "3rd Quarter Draw No Bet": ("DNB_Q3", _TWO_WAY_LABELS),
    "4th Quarter Draw No Bet": ("DNB_Q4", _TWO_WAY_LABELS),
}
_BASKETBALL_TOTALS: dict[str, str] = {
    "Total Points": "OU",
    "1st Half Total Points": "OU_HT",
    "2nd Half Total Points Over/Under (Including OT)": "OU_2H",
    "1st Quarter Total Points": "OU_Q1",
    "2nd Quarter Total Points": "OU_Q2",
    "3rd Quarter Total Points": "OU_Q3",
    "4th Quarter Total Points": "OU_Q4",
}
_BASKETBALL_HANDICAPS: dict[str, str] = {
    "Point Spread": "AH",
    "1st Half Point Spread": "AH_HT",
    "2nd Half Point Spread (Including Overtime)": "AH_2H",
    "1st Quarter Point Spread": "AH_Q1",
    "2nd Quarter Point Spread": "AH_Q2",
    "3rd Quarter Point Spread": "AH_Q3",
    "4th Quarter Point Spread": "AH_Q4",
}
_TENNIS_FIXED: dict[str, tuple[str, tuple[str, dict[str, str]]]] = {
    "Which player will win the match?": ("ML", _TWO_WAY_LABELS),
    "Set Winner (Set 1)": ("ML_SET1", _TWO_WAY_LABELS),
    "Set Winner (Set 2)": ("ML_SET2", _TWO_WAY_LABELS),
}
_TENNIS_TOTALS: dict[str, str] = {"Total": "OU"}
_TENNIS_HANDICAPS: dict[str, str] = {"Game Handicap": "AH"}
# sport -> (mercados de resultado fijo, mercados de más/menos, mercados de hándicap por líneas)
_SPORT_TABLES = {
    "baloncesto": (_BASKETBALL_FIXED, _BASKETBALL_TOTALS, _BASKETBALL_HANDICAPS),
    "tenis": (_TENNIS_FIXED, _TENNIS_TOTALS, _TENNIS_HANDICAPS),
}
# Lado de una selección de hándicap sin `type` (tenis): el nombre empieza por "1 " o "2 ".
_HANDICAP_SIDE_RE = re.compile(r"^\s*([12])\s")

# El hándicap de 2 vías (el que cruza, ver docstring) solo se ha visto de partido
# completo, con una única línea por partido (no agrupado por varias líneas).
_HANDICAP_2WAY_MARKET = "Handicap 2-Way"


class Sport888Provider(OddsProvider):
    """888sport: 1X2 y otros mercados pre-partido de LaLiga por la API JSON de su
    plataforma Spectate, leída desde dentro de una página ya cargada del
    navegador (no una petición HTTP suelta, que da 403). Ver docstring del
    módulo."""

    name = "888sport"
    uses_browser = True  # lanza Chromium: el escaneo limita cuantos a la vez (MAX_CONCURRENT_FETCHES)

    def __init__(
        self,
        tournaments: dict[str, list[tuple[str, str, str]]] | None = None,
        lobby_url: str = LOBBY_URL,
        horizon_hours: int | None = None,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        # Con `tournaments` explícito solo se leen esos torneos (modo antiguo, de LaLiga); sin él
        # se descubren todos los partidos de cada deporte por el listado por día (ver docstring).
        self.discover = tournaments is None
        self.tournaments = tournaments or DEFAULT_TOURNAMENTS
        self.lobby_url = lobby_url
        self.horizon_hours = horizon_hours or int(os.environ.get("SPORT888_HORIZON_HOURS", DEFAULT_HORIZON_HOURS))
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        if self.discover:
            requested = [k for k in dict.fromkeys(key.split("_", 1)[0] for key in sports) if k in API_SPORTS]
            return await self._discover_markets(requested) if requested else []
        wanted = [(sport, tournament) for sport in sports for tournament in self.tournaments.get(sport, [])]
        if not wanted:
            return []
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            await page.goto(self.lobby_url, timeout=20000, wait_until="load")
            await page.wait_for_timeout(2000)  # deja terminar el chequeo de sesión/antifraude propio
            for sport, tournament in wanted:
                api_sport, country, tournament_slug = tournament
                url = f"{API_BASE}{api_sport}/{country}/{tournament_slug}"
                data = await page.evaluate(_FETCH_JS, url)
                if not data:
                    continue
                events = self._parse_events(data, sport)
                markets.extend(market for _, market, _, _ in events if market is not None)
                markets.extend(await self._fetch_event_extras(page, events, tournament, sport))
            await browser.close()
        return markets

    async def _discover_markets(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            await page.goto(self.lobby_url, timeout=20000, wait_until="load")
            await page.wait_for_timeout(2000)  # deja terminar el chequeo de sesión/antifraude propio
            for sport in sports:
                try:
                    markets.extend(await self._discover_sport(page, sport))
                except Exception:
                    logger.warning("888sport: fallo leyendo %s", sport, exc_info=True)
            await browser.close()
        return markets

    async def _discover_sport(self, page, sport: str) -> list[Market]:
        raw_events: dict = {}
        for day in UPCOMING_DAYS:
            data = await page.evaluate(_FETCH_JS, f"{UPCOMING_BASE}{API_SPORTS[sport]}/{day}")
            if data:
                raw_events.update(data.get("events") or {})
        events = self._parse_upcoming({"events": raw_events}, sport)
        logger.info("888sport: %d partidos de %s pre-partido en las próximas %d h", len(events), sport, self.horizon_hours)
        markets = [event["market"] for event in events if event["market"] is not None]
        for start in range(0, len(events), EXTRAS_CHUNK):
            chunk = events[start : start + EXTRAS_CHUNK]
            results = await page.evaluate(
                _FETCH_EXTRAS_JS, {"items": [{"id": str(e["id"]), "url": e["url"]} for e in chunk], "concurrency": 5}
            )
            for event in chunk:
                data = results.get(str(event["id"]))
                if not data or data.get("error"):
                    continue
                extras = self._parse_event_extras(data, event["name"], sport)
                for market in extras:
                    market.start_time = event["start"]
                markets.extend(extras)
        return markets

    def _parse_upcoming(self, data: dict, sport: str) -> list[dict]:
        """Partidos pre-partido de `getUpcomingEvents` dentro del horizonte y sin virtuales ni
        (fútbol) femenino: {nombre, id, url de la ficha, hora, mercado 1X2 del listado o None}."""
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)
        result = []
        for event in data.get("events", {}).values():
            if event.get("event_status") != "PENDING" or event.get("inplay") is not False:
                continue
            competitors = event.get("competitors", {})
            if len(competitors) != 2:
                continue
            home = next((c.get("name") for c in competitors.values() if c.get("is_home_team")), None)
            away = next((c.get("name") for c in competitors.values() if not c.get("is_home_team")), None)
            start = self._parse_start_time(event.get("start_time"))
            slugs = [event.get(k) for k in ("sport_slug", "category_slug", "tournament_slug", "slug")]
            if not home or not away or start is None or not all(slugs) or event.get("id") is None:
                continue
            if not (now < start <= limit):
                continue
            if is_excluded(
                [event.get("tournament_name"), event.get("category_name"), home, away],
                self.exclude_esports,
                self.exclude_women,
                sport=sport,
            ):
                continue
            name = f"{home} vs. {away}"
            market = self._main_1x2(event, name, sport) if sport == "futbol" else None
            url = EVENT_DATA_BASE + "/".join(str(x) for x in slugs) + f"/{event['id']}"
            result.append({"name": name, "id": event["id"], "url": url, "start": start, "market": market})
        return result

    async def _fetch_event_extras(
        self, page, events: list[tuple[str, Market | None, str | None, object]], tournament: tuple[str, str, str], sport: str
    ) -> list[Market]:
        api_sport, country, tournament_slug = tournament
        items = [
            {"id": str(event_id), "url": f"{EVENT_DATA_BASE}{api_sport}/{country}/{tournament_slug}/{slug}/{event_id}"}
            for _, _, slug, event_id in events
            if slug and event_id is not None
        ]
        if not items:
            return []
        results = await page.evaluate(_FETCH_EXTRAS_JS, {"items": items, "concurrency": 5})
        markets: list[Market] = []
        for event_name, _, slug, event_id in events:
            if not slug or event_id is None:
                continue
            data = results.get(str(event_id))
            if not data or data.get("error"):
                continue
            markets.extend(self._parse_event_extras(data, event_name, sport))
        return markets

    def _parse_events(self, data: dict, sport: str) -> list[tuple[str, Market | None, str | None, object]]:
        """(nombre del evento, mercado 1X2 o None, slug de su ficha o None, id del
        evento o None) por cada partido bruto del listado."""
        events = []
        for event in data.get("events", {}).values():
            if event.get("event_status") != "PENDING" or event.get("inplay") is not False:
                continue
            competitors = event.get("competitors", {})
            if len(competitors) != 2:
                continue
            home = next((c.get("name") for c in competitors.values() if c.get("is_home_team")), None)
            away = next((c.get("name") for c in competitors.values() if not c.get("is_home_team")), None)
            if not home or not away:
                continue
            event_name = f"{home} vs. {away}"
            events.append((event_name, self._main_1x2(event, event_name, sport), event.get("slug"), event.get("id")))
        return events

    def _main_1x2(self, event: dict, event_name: str, sport: str) -> Market | None:
        """Mercado 1X2 ("Ganador del partido") que trae el propio listado de un partido."""
        market_data = next((m for m in event.get("markets", {}).values() if m.get("name") == _MAIN_MARKET_NAME), None)
        if market_data is None or not market_data.get("active") or not market_data.get("betable"):
            return None
        outcomes = self._parse_1x2(market_data.get("selections", {}))
        if outcomes is None:
            return None
        return Market(
            event=event_name,
            sport=sport,
            market_type="1X2",
            outcomes=outcomes,
            start_time=self._parse_start_time(event.get("start_time")),
        )

    def _parse_1x2(self, selections: dict) -> list[Outcome] | None:
        by_type: dict[str, float] = {}
        for selection in selections.values():
            sel_type = selection.get("type")
            if sel_type not in _1X2_TYPES or sel_type in by_type:
                return None
            if not selection.get("active") or not selection.get("betable") or not selection.get("tradable"):
                return None
            try:
                price = float(selection["decimal_price"])
            except (KeyError, TypeError, ValueError):
                return None
            if price <= 1.0:
                return None
            by_type[sel_type] = price
        if set(by_type) != set(_1X2_TYPES):
            return None
        return [Outcome(name=t, bookmaker=self.name, odds=by_type[t]) for t in _1X2_TYPES]

    def _parse_event_extras(self, data: dict, event_name: str, sport: str) -> list[Market]:
        event = data.get("event") if isinstance(data, dict) else None
        if not event:
            return []
        selections_by_id = ((event.get("markets") or {}).get("markets_selections")) or {}
        by_name = self._selections_by_name(selections_by_id)
        markets: list[Market] = []
        if sport in _SPORT_TABLES:
            return self._parse_sport_extras(by_name, event_name, sport)
        for market_name, (market_type, (key_field, label_map)) in _FIXED_MARKETS.items():
            selections = by_name.get(market_name)
            if selections is None:
                continue
            market = self._parse_fixed_market(selections, key_field, label_map, market_type, event_name, sport)
            if market is not None:
                markets.append(market)
        for market_name, prefix in _TOTAL_MARKETS.items():
            selections = by_name.get(market_name)
            if selections is not None:
                markets.extend(self._parse_total_market(selections, prefix, event_name, sport))
        ah_selections = by_name.get(_HANDICAP_2WAY_MARKET)
        if ah_selections is not None:
            ah_market = self._parse_handicap_2way(ah_selections, event_name, sport)
            if ah_market is not None:
                markets.append(ah_market)
        return markets

    def _parse_sport_extras(self, by_name: dict[str, list[dict]], event_name: str, sport: str) -> list[Market]:
        """Mercados de baloncesto y tenis por las tablas `_SPORT_TABLES` (nombres exactos)."""
        fixed, totals, handicaps = _SPORT_TABLES[sport]
        markets: list[Market] = []
        for market_name, (market_type, (key_field, label_map)) in fixed.items():
            selections = by_name.get(market_name)
            if selections is not None:
                market = self._parse_fixed_market(selections, key_field, label_map, market_type, event_name, sport)
                if market is not None:
                    markets.append(market)
        for market_name, prefix in totals.items():
            selections = by_name.get(market_name)
            if selections is not None:
                markets.extend(self._parse_total_market(selections, prefix, event_name, sport))
        for market_name, prefix in handicaps.items():
            selections = by_name.get(market_name)
            if selections is not None:
                markets.extend(self._parse_handicap_lines(selections, prefix, event_name, sport))
        return markets

    def _parse_handicap_lines(self, selections: list[dict], prefix: str, event_name: str, sport: str) -> list[Market]:
        """Hándicap de varias líneas en un mismo mercado: empareja el lado local ("1") y el
        visitante ("2") de cada línea, expresada desde el local (la del visitante, con el signo
        cambiado). El lado sale de `type` o, sin él (tenis), del "1 "/"2 " con que empieza el nombre."""
        by_line: dict[float, dict[str, float]] = {}
        for sel in selections:
            if not (sel.get("active") and sel.get("betable") and sel.get("tradable")):
                continue
            side = sel.get("type")
            if side not in ("1", "2"):
                match = _HANDICAP_SIDE_RE.match(str(sel.get("selection_db_name") or sel.get("name") or ""))
                side = match.group(1) if match else None
            try:
                line = float(sel["special_odds_value"])
                price = float(sel["decimal_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if side is None or price <= 1.0:
                continue
            by_line.setdefault(line if side == "1" else -line, {})[side] = price
        markets = []
        for line, sides in sorted(by_line.items()):
            if set(sides) != {"1", "2"}:
                continue
            outcomes = [
                Outcome(name="1", bookmaker=self.name, odds=sides["1"]),
                Outcome(name="2", bookmaker=self.name, odds=sides["2"]),
            ]
            markets.append(
                Market(event=event_name, sport=sport, market_type=f"{prefix}_{self._fmt_line(line, signed=True)}", outcomes=outcomes)
            )
        return markets

    @staticmethod
    def _selections_by_name(selections_by_id: dict) -> dict[str, list[dict]]:
        """`markets_selections` viene keyed por market_id (no estable entre
        partidos): se reindexa por `market_name` (inglés, estable) para
        clasificar. Un mercado sin selecciones tras aplanar (todo suspendido) no
        entra."""
        result: dict[str, list[dict]] = {}
        for raw in selections_by_id.values():
            flat = Sport888Provider._flatten_selections(raw)
            if not flat:
                continue
            name = flat[0].get("market_name")
            if name and name not in result:
                result[name] = flat
        return result

    @staticmethod
    def _flatten_selections(raw) -> list[dict]:
        """Todas las selecciones (dicts con `decimal_price`) de un mercado, sea cual sea su forma:
        lista plana; {"<línea>": {"<lado>": selección}, ..., "grouped": true} (más/menos); o lista
        de {"<línea>": [selecciones]} (hándicap de varias líneas). Ver docstring del módulo."""
        flat: list[dict] = []

        def walk(node) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                if "decimal_price" in node:
                    flat.append(node)
                else:
                    for key, value in node.items():
                        if key != "grouped":
                            walk(value)

        walk(raw)
        return flat

    def _parse_fixed_market(
        self, selections: list[dict], key_field: str, label_map: dict[str, str], market_type: str, event_name: str, sport: str
    ) -> Market | None:
        by_name: dict[str, float] = {}
        for sel in selections:
            if not (sel.get("active") and sel.get("betable") and sel.get("tradable")):
                return None
            name = label_map.get(sel.get(key_field))
            try:
                price = float(sel["decimal_price"])
            except (KeyError, TypeError, ValueError):
                return None
            if name is None or price <= 1.0 or name in by_name:
                return None
            by_name[name] = price
        if set(by_name) != set(label_map.values()):
            return None
        outcomes = [Outcome(name=n, bookmaker=self.name, odds=by_name[n]) for n in label_map.values()]
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    def _parse_total_market(self, selections: list[dict], prefix: str, event_name: str, sport: str) -> list[Market]:
        by_line: dict[float, dict[str, float]] = {}
        for sel in selections:
            if not (sel.get("active") and sel.get("betable") and sel.get("tradable")):
                continue
            side = sel.get("type")
            if side not in ("Over", "Under"):
                continue
            try:
                line = float(sel["special_odds_value"])
                price = float(sel["decimal_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 1.0:
                continue
            by_line.setdefault(line, {})[side] = price
        markets = []
        for line, sides in sorted(by_line.items()):
            if set(sides) != {"Over", "Under"}:
                continue
            outcomes = [
                Outcome(name="Over", bookmaker=self.name, odds=sides["Over"]),
                Outcome(name="Under", bookmaker=self.name, odds=sides["Under"]),
            ]
            markets.append(
                Market(event=event_name, sport=sport, market_type=f"{prefix}_{self._fmt_line(line)}", outcomes=outcomes)
            )
        return markets

    def _parse_handicap_2way(self, selections: list[dict], event_name: str, sport: str) -> Market | None:
        by_type: dict[str, tuple[float, float]] = {}
        for sel in selections:
            if not (sel.get("active") and sel.get("betable") and sel.get("tradable")):
                return None
            sel_type = sel.get("type")
            if sel_type not in ("1", "2") or sel_type in by_type:
                return None
            try:
                line = float(sel["special_odds_value"])
                price = float(sel["decimal_price"])
            except (KeyError, TypeError, ValueError):
                return None
            if price <= 1.0:
                return None
            by_type[sel_type] = (line, price)
        if set(by_type) != {"1", "2"}:
            return None
        home_line, home_price = by_type["1"]
        away_line, away_price = by_type["2"]
        if home_line != -away_line:
            return None  # líneas inconsistentes entre lados: mercado no fiable
        outcomes = [
            Outcome(name="1", bookmaker=self.name, odds=home_price),
            Outcome(name="2", bookmaker=self.name, odds=away_price),
        ]
        market_type = f"AH_{self._fmt_line(home_line, signed=True)}"
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    @staticmethod
    def _fmt_line(value: float, signed: bool = False) -> str:
        text = str(int(value)) if value == int(value) else f"{value:g}"
        return "+" + text if signed and value > 0 else text

    @staticmethod
    def _parse_start_time(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
