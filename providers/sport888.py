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

Estructura de la respuesta, verificada en vivo:

- `events`: dict `id -> evento`. Cada evento trae `event_status` ("PENDING" para
  pre-partido) e `inplay` (bool) — se descartan los que no sean exactamente
  pre-partido. `competitors`: dict de 2 competidores con `name` e `is_home_team`
  (identifica local/visitante sin ambigüedad, a diferencia de casas que solo dan
  el nombre en un orden esperado). `start_time`: ISO 8601 con timezone.
- `markets`: dict `id -> mercado` por evento; en esta llamada solo trae el mercado
  por defecto, `name == "Ganador del partido"` (1X2). `selections`: dict de
  selecciones con `type` ("1"/"X"/"2"), `decimal_price` (string) y los flags
  `active`/`betable`/`tradable`.
- Solo 1X2 de LaLiga por ahora (mismo alcance inicial que tuvo Sportium/Betfair);
  otros mercados del mismo evento (más/menos, hándicap...) no explorados todavía,
  y otras competiciones tendrían su propio slug de torneo por confirmar.
"""

import asyncio

from datetime import datetime

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

LOBBY_URL = "https://www.888sport.es/futbol/espana/la-liga/"
API_BASE = "https://spectate-web.888sport.es/spectate/sportsbook-req/getTournamentMatches/"

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


class Sport888Provider(OddsProvider):
    """888sport: 1X2 pre-partido de LaLiga por la API JSON de su plataforma
    Spectate, leída desde dentro de una página ya cargada del navegador (no una
    petición HTTP suelta, que da 403). Ver docstring del módulo."""

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
            for sport, (api_sport, country, tournament) in wanted:
                url = f"{API_BASE}{api_sport}/{country}/{tournament}"
                data = await page.evaluate(_FETCH_JS, url)
                if data:
                    markets.extend(self._parse_events(data, sport))
            await browser.close()
        return markets

    def _parse_events(self, data: dict, sport: str) -> list[Market]:
        markets = []
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
            market_data = next(
                (m for m in event.get("markets", {}).values() if m.get("name") == _MAIN_MARKET_NAME), None
            )
            if market_data is None or not market_data.get("active") or not market_data.get("betable"):
                continue
            outcomes = self._parse_1x2(market_data.get("selections", {}))
            if outcomes is None:
                continue
            markets.append(
                Market(
                    event=f"{home} vs. {away}",
                    sport=sport,
                    market_type="1X2",
                    outcomes=outcomes,
                    start_time=self._parse_start_time(event.get("start_time")),
                )
            )
        return markets

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

    @staticmethod
    def _parse_start_time(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
