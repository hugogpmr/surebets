import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.betfair.es/apuestas/f%C3%BAtbol/la-liga-espa%C3%B1ola/c-117",
}

# Betfair usa CSS-modules con prefijos hash que cambian entre despliegues
# (ej. "c84e4011151df22b-label"), así que se hace coincidir por el SUFIJO
# semántico de cada clase en vez del hash completo, comprobando cada token
# de classList por separado (una cuota tiene dos clases a la vez, p.ej.
# "c84e...-label c84e...-labelTwoLines", así que no vale un simple $=).
_EXTRACT_MATCHES_JS = """() => {
    const rows = document.querySelectorAll('[class*="-fixture"][class*="viewCoupon"]');
    const results = [];
    for (const row of rows) {
        let scope = row;
        for (let i = 0; i < 4 && scope; i++) scope = scope.parentElement;
        const teams = Array.from(row.querySelectorAll('[class*="-teamNameLabel"]'))
            .map(e => e.textContent.trim());
        const buttons = scope ? scope.querySelectorAll('[class*="-betButtonContainer"]') : [];
        const odds = [];
        for (const b of buttons) {
            let value = null;
            for (const span of b.querySelectorAll('span')) {
                if (Array.from(span.classList).some(c => c.endsWith('-label'))) {
                    value = span.textContent.trim();
                    break;
                }
            }
            odds.push(value);
        }
        if (teams.length === 2 && odds.length >= 3 && odds.slice(0, 3).every(o => o !== null)) {
            results.push({ teams, odds: odds.slice(0, 3) });
        }
    }
    return results;
}"""

# Mismo patrón que _EXTRACT_MATCHES_JS, pero con el mercado "Más/Menos de 2,5
# Goles" ya seleccionado (ver _fetch_over_under): solo 2 botones por partido
# (Más de / Menos de), en ese orden.
_EXTRACT_OU_MATCHES_JS = """() => {
    const rows = document.querySelectorAll('[class*="-fixture"][class*="viewCoupon"]');
    const results = [];
    for (const row of rows) {
        let scope = row;
        for (let i = 0; i < 4 && scope; i++) scope = scope.parentElement;
        const teams = Array.from(row.querySelectorAll('[class*="-teamNameLabel"]'))
            .map(e => e.textContent.trim());
        const buttons = scope ? scope.querySelectorAll('[class*="-betButtonContainer"]') : [];
        const odds = [];
        for (const b of buttons) {
            let value = null;
            for (const span of b.querySelectorAll('span')) {
                if (Array.from(span.classList).some(c => c.endsWith('-label'))) {
                    value = span.textContent.trim();
                    break;
                }
            }
            odds.push(value);
        }
        if (teams.length === 2 && odds.length >= 2 && odds.slice(0, 2).every(o => o !== null)) {
            results.push({ teams, odds: odds.slice(0, 2) });
        }
    }
    return results;
}"""


class BetfairProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Betfair: cuotas 1X2 visibles sin
    login ni protección anti-bot activa (verificado en vivo).

    Estructura verificada: cada partido es un bloque [class*="-fixture"]
    (variante "viewCoupon" en el listado de competición) con los nombres de
    equipo en [class*="-teamNameLabel"]; los tres botones de cuota (1/X/2)
    están en un contenedor hermano [class*="-betButtonContainer"] cuatro
    niveles por encima del bloque del partido.

    También implementa el mercado fijo "Más/Menos de 2,5 Goles" (over/under):
    a diferencia de Sportium, aquí la línea es una opción de menú explícita
    (no una sugerencia que varía por partido), así que el market_type es
    siempre "OU_2.5". El cambio de mercado no tiene URL propia (estado de
    cliente), así que hay que simular el click en el selector de mercado
    [class*="-marketSwitcher"] y luego en la opción
    label[for="ppb:marketType:OVER_UNDER_25"] (identificador semántico
    estable, a diferencia de las clases con hash).
    """

    name = "betfair"

    def __init__(self, competition_urls: dict[str, str] | None = None):
        self.competition_urls = competition_urls or DEFAULT_COMPETITION_URLS

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for sport in sports:
                url = self.competition_urls.get(sport)
                if not url:
                    continue
                await page.goto(url, timeout=20000)
                await page.wait_for_selector('[class*="-betButtonContainer"]', timeout=20000)
                await page.wait_for_timeout(1500)
                raw_matches = await page.evaluate(_EXTRACT_MATCHES_JS)
                markets.extend(self._parse_matches(raw_matches, sport))

                markets.extend(await self._fetch_over_under(page, sport))
            await browser.close()
        return markets

    async def _fetch_over_under(self, page, sport: str) -> list[Market]:
        try:
            # El banner de cookies (OneTrust) tapa el selector de mercado la
            # primera vez; "Permitir solo las cookies necesarias" es la
            # opción menos intrusiva. Si no aparece (ya aceptado antes en
            # esta misma page), se ignora el timeout y se sigue.
            try:
                await page.click("#onetrust-reject-all-handler", timeout=3000)
            except Exception:
                pass
            await page.click('button[class*="-marketSwitcher"]', timeout=5000)
            await page.click('label[for="ppb:marketType:OVER_UNDER_25"]', timeout=5000)
            await page.wait_for_timeout(1500)
            raw_matches = await page.evaluate(_EXTRACT_OU_MATCHES_JS)
        except Exception:
            return []
        return self._parse_over_under_matches(raw_matches, sport)

    def _parse_matches(self, raw_matches: list[dict], sport: str) -> list[Market]:
        markets = []
        for match in raw_matches:
            teams = match.get("teams", [])
            odds = match.get("odds", [])
            if len(teams) != 2 or len(odds) < 3:
                continue
            try:
                outcomes = [
                    Outcome(name="1", bookmaker=self.name, odds=float(odds[0])),
                    Outcome(name="X", bookmaker=self.name, odds=float(odds[1])),
                    Outcome(name="2", bookmaker=self.name, odds=float(odds[2])),
                ]
            except ValueError:
                continue
            event_name = f"{teams[0]} vs. {teams[1]}"
            markets.append(Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes))
        return markets

    def _parse_over_under_matches(self, raw_matches: list[dict], sport: str) -> list[Market]:
        markets = []
        for match in raw_matches:
            teams = match.get("teams", [])
            odds = match.get("odds", [])
            if len(teams) != 2 or len(odds) < 2:
                continue
            try:
                outcomes = [
                    Outcome(name="Over", bookmaker=self.name, odds=float(odds[0])),
                    Outcome(name="Under", bookmaker=self.name, odds=float(odds[1])),
                ]
            except ValueError:
                continue
            event_name = f"{teams[0]} vs. {teams[1]}"
            markets.append(Market(event=event_name, sport=sport, market_type="OU_2.5", outcomes=outcomes))
        return markets
