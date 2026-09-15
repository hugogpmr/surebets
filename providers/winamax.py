import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.winamax.es/apuestas-deportivas/sports/1/32/36",
}

# Winamax usa cuotas con coma decimal ("1,36") y styled-components con clases
# hash que cambian entre despliegues, pero mantiene un puñado de clases
# semánticas estables: .card-wrapper (partido), .bet-group-template (mercado,
# 3 outcomes = 1X2), .odd-button-wrapper (cada botón) y .odd-button-value
# (la cuota). El nombre del resultado no tiene clase propia, así que se
# extrae filtrando del texto del wrapper las líneas puramente numéricas o con
# "%" (son el contador de apuestas y el % de distribución, no el nombre).
_EXTRACT_MATCHES_JS = """() => {
    const cards = document.querySelectorAll('.card-wrapper');
    const results = [];
    for (const card of cards) {
        const group = card.querySelector('.bet-group-template');
        if (!group) continue;
        const wrappers = group.querySelectorAll('.odd-button-wrapper');
        const outcomes = Array.from(wrappers).map(w => {
            const lines = w.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
            const label = lines.find(l => !/^\\d+%?$/.test(l) && !/^\\d+[,.]\\d+$/.test(l));
            const valueEl = w.querySelector('.odd-button-value');
            return { label: label || null, value: valueEl ? valueEl.textContent.trim() : null };
        });
        results.push({ outcomes });
    }
    return results;
}"""


class WinamaxProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Winamax: cuotas 1X2 visibles sin
    login ni protección anti-bot activa (verificado en vivo). Usa coma
    decimal española ("1,36"), convertida a float en el parseo.
    """

    name = "winamax"

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
                await page.wait_for_selector(".odd-button-value", timeout=20000)
                await page.wait_for_timeout(1500)
                raw_matches = await page.evaluate(_EXTRACT_MATCHES_JS)
                markets.extend(self._parse_matches(raw_matches, sport))
            await browser.close()
        return markets

    def _parse_matches(self, raw_matches: list[dict], sport: str) -> list[Market]:
        markets = []
        for match in raw_matches:
            outcomes_raw = match.get("outcomes", [])
            if len(outcomes_raw) != 3 or outcomes_raw[1].get("label") != "Empate":
                continue
            home, draw, away = outcomes_raw
            if not all(o.get("label") and o.get("value") for o in (home, draw, away)):
                continue
            try:
                outcomes = [
                    Outcome(name="1", bookmaker=self.name, odds=self._to_float(home["value"])),
                    Outcome(name="X", bookmaker=self.name, odds=self._to_float(draw["value"])),
                    Outcome(name="2", bookmaker=self.name, odds=self._to_float(away["value"])),
                ]
            except ValueError:
                continue
            event_name = f"{home['label']} vs. {away['label']}"
            markets.append(Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes))
        return markets

    @staticmethod
    def _to_float(value: str) -> float:
        return float(value.replace(",", "."))
