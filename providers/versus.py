import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.versus.es/apuestas/sports/soccer/competitions/454900/matches",
}

# Mismo desplegable .ta-DropdownControl que 1X2: item de clase ta-item-<X> ->
# (market_type, código interno ta-MarketType-<Y>, nombres de resultado en el orden
# en que Versus pinta los botones). Los nombres de los ítems del desplegable son
# distintos a los de Sportium/Marca Apuestas ("TotaldeGoles" en vez de
# "GolesTotales", "Resultadoeneldescanso" en vez de "Resultadoaldescanso"), pero
# los códigos internos (BTSC/H1RS) son los mismos - confirma el mismo backend.
# Verificado en vivo el 2026-09-24: esta casa SÍ tiene un cuarto ítem, "Hndicap"
# (código HCMR), pero es un hándicap de 3 vías con ajuste de marcador (empate
# posible, como el "Hándicap" de score de Zebet) - ninguna otra fuente de este
# repo lo emite, así que se descarta a propósito (sin Doble Oportunidad tampoco,
# igual que Marca Apuestas: no está en el desplegable).
SIMPLE_MARKETS: dict[str, tuple[str, str, list[str]]] = {
    "AmbosMarcan": ("BTTS", "BTSC", ["Yes", "No"]),
    "Resultadoeneldescanso": ("1X2_HT", "H1RS", ["1", "X", "2"]),
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

_EXTRACT_MARKET_EVENTS_JS = """(group, marketType) => {
    const items = Array.from(group.querySelectorAll('.ta-EventListItemDetails, .ta-Market'));
    const events = [];
    let current = null;
    for (const el of items) {
        if (el.classList.contains('ta-EventListItemDetails')) {
            const teams = Array.from(el.querySelectorAll('.ta-ParticipantItem'))
                .map(t => t.textContent.trim());
            current = { teams, odds: [] };
            events.push(current);
        } else if (current && el.classList.contains('ta-MarketType-' + marketType)) {
            current.odds = Array.from(el.querySelectorAll('.ta-SelectionButtonView'))
                .map(b => b.textContent.trim());
        }
    }
    return events;
}"""

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


class VersusProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Versus.

    Descubrimiento 2026-09-24 (se venía marcando como "carga, pero sin JSON de
    cuotas evidente" desde 2026-09-21 - nunca se había probado a fondo). Un
    `chromium.launch(headless=True)` real, sin trucos, carga con status 200 y sin
    ningún reto (Cloudflare/CAPTCHA/WAF): resultó ser **el mismo framework "ta-"
    que ya usan `providers/sportium.py` y `providers/marcaapuestas.py`** (mismas
    clases CSS y mismos códigos internos `ta-MarketType-BTSC`/`ta-MarketType-H1RS`
    para Ambos Marcan/Resultado al descanso), verificado con JavaScript en vivo
    contra la competición de LaLiga (id 454900 en la URL, confirmado con los
    nombres de equipo del listado). Por eso esta clase es casi una copia de
    `SportiumProvider`: 1X2, Goles Totales (over/under), Ambos Marcan (BTTS) y
    Resultado al descanso (1X2_HT). Sin Doble Oportunidad (no está en el
    desplegable) ni Hándicap (el "Hndicap" de esta casa es de 3 vías con ajuste de
    marcador, no el hándicap asiático de 2 vías del resto de fuentes - ver
    docstring de `SIMPLE_MARKETS`).
    """

    name = "versus"

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
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_selector(".ta-EventListGroup", timeout=20000)
                await page.wait_for_selector(".ta-SelectionButtonView", timeout=20000)
                raw_events = await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_EVENTS_JS)
                markets.extend(self._parse_events(raw_events, sport))

                markets.extend(await self._fetch_over_under(page, sport))

                for item_class, (market_type, code, outcome_names) in SIMPLE_MARKETS.items():
                    raw_events = await self._fetch_simple_market(page, item_class, code)
                    markets.extend(self._parse_simple_market(raw_events, sport, market_type, outcome_names))
            await browser.close()
        return markets

    async def _fetch_over_under(self, page, sport: str) -> list[Market]:
        try:
            await page.click(".ta-DropdownControl", timeout=5000)
            await page.click(".ta-item-TotaldeGoles", timeout=5000)
            await page.wait_for_timeout(800)
            raw_events = await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_OU_EVENTS_JS)
        except Exception:
            return []
        return self._parse_over_under_events(raw_events, sport)

    async def _fetch_simple_market(self, page, item_class: str, code: str) -> list[dict]:
        try:
            await page.click(".ta-DropdownControl", timeout=5000)
            await page.click(f".ta-item-{item_class}", timeout=5000)
            await page.wait_for_timeout(800)
            return await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_MARKET_EVENTS_JS, code)
        except Exception:
            return []

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

    def _parse_simple_market(
        self, raw_events: list[dict], sport: str, market_type: str, outcome_names: list[str]
    ) -> list[Market]:
        markets = []
        for event in raw_events:
            teams = event.get("teams", [])
            odds = event.get("odds", [])
            if len(teams) != 2 or len(odds) != len(outcome_names):
                continue
            try:
                outcomes = [Outcome(name=name, bookmaker=self.name, odds=float(o)) for name, o in zip(outcome_names, odds)]
            except ValueError:
                continue
            event_name = f"{teams[0]} vs. {teams[1]}"
            markets.append(Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes))
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
