import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

BASE_URL = "https://apuestas.kirolbet.es/Api/esp/Lib/Competicion"
HOME_URL = "https://apuestas.kirolbet.es/"


class KirolbetProvider(OddsProvider):
    """Scraper vía la API JSON de Kirolbet (/Api/esp/Lib/Competicion?id=X).

    La API está detrás de un reto anti-bot basado en JavaScript: una petición
    HTTP simple (httpx) recibe 403 incluso en la portada, desde cualquier IP,
    porque no puede resolver el reto. Por eso se usa Playwright: se carga la
    home una vez (el navegador resuelve el reto y obtiene cookies de sesión
    válidas) y luego se reutiliza ese contexto para llamar a la API.
    """

    name = "kirolbet"

    def __init__(self, competition_ids: dict[str, int]):
        self.competition_ids = competition_ids

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(HOME_URL, wait_until="networkidle")

            for sport in sports:
                comp_id = self.competition_ids.get(sport)
                if comp_id is None:
                    continue
                resp = await context.request.get(BASE_URL, params={"id": comp_id})
                if not resp.ok:
                    continue
                markets.extend(self._parse_events(await resp.json(), sport))

            await browser.close()
        return markets

    def _parse_events(self, data: dict, sport: str) -> list[Market]:
        markets = []
        for event in data.get("LstEve") or []:
            event_name = event.get("DesEve", "")
            for market in event.get("Markets", []):
                market_type = self._normalize_market_type(market.get("DesMod", ""))
                if market_type is None:
                    continue
                outcomes = [
                    Outcome(name=p["DesPro"], bookmaker=self.name, odds=float(p["CoefCanal"]))
                    for p in market.get("Pronosticos", [])
                    if p.get("CoefCanal")
                ]
                if outcomes:
                    markets.append(
                        Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)
                    )
        return markets

    @staticmethod
    def _normalize_market_type(des_mod: str) -> str | None:
        if des_mod == "1X2":
            return "1X2"
        if des_mod.startswith("Nº Goles (2,5)"):
            return "OU_2.5"
        return None
