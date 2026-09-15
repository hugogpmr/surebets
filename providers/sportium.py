import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.sportium.es/apuestas/sports/soccer/competitions/45211/matches",
}

_EXTRACT_EVENTS_JS = """(group) => {
    const items = Array.from(group.querySelectorAll(
        '.ta-EventListItemDetails, .ta-SelectionButtonView'
    ));
    const events = [];
    let current = null;
    for (const el of items) {
        if (el.classList.contains('ta-EventListItemDetails')) {
            const teams = Array.from(el.querySelectorAll('.ta-ParticipantItem'))
                .map(t => t.textContent.trim());
            current = { teams, odds: [] };
            events.push(current);
        } else if (current) {
            current.odds.push(el.textContent.trim());
        }
    }
    return events;
}"""

# Mercado "Goles Totales" (over/under): cada botón concatena línea y cuota en
# el mismo texto ("2.5" + "1.70" sin separador), pero por dentro son dos nodos
# separados: .ta-infoTextHandicap (línea) y .ta-price_text (cuota).
_EXTRACT_OU_EVENTS_JS = """(group) => {
    const items = Array.from(group.querySelectorAll(
        '.ta-EventListItemDetails, .ta-SelectionButtonView'
    ));
    const events = [];
    let current = null;
    for (const el of items) {
        if (el.classList.contains('ta-EventListItemDetails')) {
            const teams = Array.from(el.querySelectorAll('.ta-ParticipantItem'))
                .map(t => t.textContent.trim());
            current = { teams, selections: [] };
            events.push(current);
        } else if (current) {
            const line = el.querySelector('.ta-infoTextHandicap');
            const value = el.querySelector('.ta-price_text');
            current.selections.push({
                line: line ? line.textContent.trim() : null,
                value: value ? value.textContent.trim() : null,
            });
        }
    }
    return events;
}"""


class SportiumProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Sportium: no expone una API de cuotas
    limpia (probablemente WebSocket), así que se lee la tabla ya renderizada.

    Verificado en vivo: contenedor .ta-EventListGroup, cada evento es un
    .ta-EventListItemDetails con equipos en .ta-ParticipantItem, seguido en el
    DOM por sus botones de cuota .ta-SelectionButtonView (1, X, 2, ...).

    Implementa 1X2 y Goles Totales (over/under). El mercado se cambia con el
    desplegable .ta-DropdownControl -> opción .ta-item-GolesTotales (misma
    página, sin recargar). La línea de goles la decide Sportium por partido
    (normalmente 2.5, pero no siempre, p.ej. 4.5 en un partido muy desigual),
    así que el market_type incluye la línea ("OU_2.5", "OU_4.5", ...) para no
    comparar cuotas de líneas distintas entre casas.
    """

    name = "sportium"

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
                await page.wait_for_selector(".ta-EventListGroup", timeout=20000)
                await page.wait_for_selector(".ta-SelectionButtonView", timeout=20000)
                raw_events = await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_EVENTS_JS)
                markets.extend(self._parse_events(raw_events, sport))

                markets.extend(await self._fetch_over_under(page, sport))
            await browser.close()
        return markets

    async def _fetch_over_under(self, page, sport: str) -> list[Market]:
        try:
            await page.click(".ta-DropdownControl", timeout=5000)
            await page.click(".ta-item-GolesTotales", timeout=5000)
            await page.wait_for_timeout(800)
            raw_events = await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_OU_EVENTS_JS)
        except Exception:
            return []
        return self._parse_over_under_events(raw_events, sport)

    def _parse_events(self, raw_events: list[dict], sport: str) -> list[Market]:
        markets = []
        for event in raw_events:
            teams = event.get("teams", [])
            odds = event.get("odds", [])
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

    def _parse_over_under_events(self, raw_events: list[dict], sport: str) -> list[Market]:
        markets = []
        for event in raw_events:
            teams = event.get("teams", [])
            selections = event.get("selections", [])
            if len(teams) != 2 or len(selections) < 2:
                continue
            line = selections[0].get("line")
            if not line or selections[1].get("line") != line:
                continue
            try:
                outcomes = [
                    Outcome(name="Over", bookmaker=self.name, odds=float(selections[0]["value"])),
                    Outcome(name="Under", bookmaker=self.name, odds=float(selections[1]["value"])),
                ]
            except (TypeError, ValueError):
                continue
            event_name = f"{teams[0]} vs. {teams[1]}"
            markets.append(
                Market(event=event_name, sport=sport, market_type=f"OU_{line}", outcomes=outcomes)
            )
        return markets
