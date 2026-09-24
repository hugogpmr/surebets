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

Solo LaLiga por ahora; otras competiciones tendrían su propio slug de torneo por
confirmar.
"""

import asyncio

from datetime import datetime

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

LOBBY_URL = "https://www.888sport.es/futbol/espana/la-liga/"
API_BASE = "https://spectate-web.888sport.es/spectate/sportsbook-req/getTournamentMatches/"
EVENT_DATA_BASE = "https://spectate-web.888sport.es/spectate/sportsbook/getEventData/"

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

# Igual que _FETCH_MANY_JS de providers/bwin.py: varios fetch() concurrentes desde
# la misma página, uno por partido, reutilizando la sesión ya establecida.
_FETCH_MANY_JS = """async ({items, concurrency}) => {
    const out = {};
    let next = 0;
    async function worker() {
        while (next < items.length) {
            const item = items[next++];
            try {
                const response = await fetch(item.url, {credentials: 'include'});
                out[item.id] = response.ok ? await response.json() : {error: response.status};
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
# El hándicap de 2 vías (el que cruza, ver docstring) solo se ha visto de partido
# completo, con una única línea por partido (no agrupado por varias líneas).
_HANDICAP_2WAY_MARKET = "Handicap 2-Way"


class Sport888Provider(OddsProvider):
    """888sport: 1X2 y otros mercados pre-partido de LaLiga por la API JSON de su
    plataforma Spectate, leída desde dentro de una página ya cargada del
    navegador (no una petición HTTP suelta, que da 403). Ver docstring del
    módulo."""

    name = "888sport"

    def __init__(self, tournaments: dict[str, list[tuple[str, str, str]]] | None = None, lobby_url: str = LOBBY_URL):
        self.tournaments = tournaments or DEFAULT_TOURNAMENTS
        self.lobby_url = lobby_url

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
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
        results = await page.evaluate(_FETCH_MANY_JS, {"items": items, "concurrency": 5})
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
            market_data = next(
                (m for m in event.get("markets", {}).values() if m.get("name") == _MAIN_MARKET_NAME), None
            )
            market = None
            if market_data is not None and market_data.get("active") and market_data.get("betable"):
                outcomes = self._parse_1x2(market_data.get("selections", {}))
                if outcomes is not None:
                    market = Market(
                        event=event_name,
                        sport=sport,
                        market_type="1X2",
                        outcomes=outcomes,
                        start_time=self._parse_start_time(event.get("start_time")),
                    )
            events.append((event_name, market, event.get("slug"), event.get("id")))
        return events

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
        """La forma normal es una lista de selecciones; los mercados con varias
        líneas (Más/Menos y variantes) vienen agrupados como
        {"<índice de línea>": {"<índice de lado>": selección, ...}, ...,
        "grouped": true} - ver docstring del módulo."""
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, dict)]
        if isinstance(raw, dict):
            flat: list[dict] = []
            for key, value in raw.items():
                if key == "grouped" or not isinstance(value, dict):
                    continue
                flat.extend(v for v in value.values() if isinstance(v, dict))
            return flat
        return []

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
