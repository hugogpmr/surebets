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


class SportiumProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Sportium: no expone una API de cuotas
    limpia (probablemente WebSocket), así que se lee la tabla ya renderizada.

    Verificado en vivo: contenedor .ta-EventListGroup, cada evento es un
    .ta-EventListItemDetails con equipos en .ta-ParticipantItem, seguido en el
    DOM por sus botones de cuota .ta-SelectionButtonView (1, X, 2, ...).

    Solo implementa 1X2 por ahora: el over/under concatena línea y cuota en el
    mismo texto ("2.5" + "1.70") sin separador fiable, pendiente de resolver.
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
            await browser.close()
        return markets

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
