import asyncio
import urllib.parse

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_LEAGUE_URLS = {
    "futbol": "https://www.cuotasahora.com/football/spain/laliga-ea-sports/",
}

# Casas que devuelve CuotasAhora (comparador, no una casa en sí) y que
# tratamos como fuente para arbitraje. Verificado a mano el 2026-09-16 contra
# el buscador oficial de la DGOJ (ordenacionjuego.es/operadores-juego/
# operadores-licencia/operadores, las 78 fichas de operadores con licencia,
# una por una): TODAS las casas de esta lista tienen licencia vigente en
# España, incluido 1xBet.es (WAGERFAIR, S.A. — pese a la sospecha inicial de
# que fuera un operador offshore sin licencia, sí la tiene). Esta
# verificación es una foto de un momento dado: la DGOJ actualiza el registro
# mensualmente, así que puede quedar desfasada — revisar de nuevo en
# ordenacionjuego.es antes de operar con dinero real si ha pasado tiempo.
#
# Sportium/Betfair/Winamax se excluyen aquí a propósito aunque aparezcan en
# la tabla: ya los scrapeamos en directo (providers/sportium.py, betfair.py,
# winamax.py) y mezclar ambas fuentes para la misma casa arriesga comparar
# una cuota fresca (scraping directo) con una del comparador que puede ir
# unos segundos/minutos por detrás.
ALLOWED_BOOKMAKERS = {
    "1xbet.es": "1xbet",
    "888sport": "888sport",
    "bet365": "bet365",
    "betway": "betway",
    "bwin.es": "bwin",
    "codere": "codere",
    "luckia.es": "luckia",
    "paf.es": "paf",
    "retabet": "retabet",
    "speedybet.es": "speedybet",
    "versus.es": "versus",
    "william hill": "williamhill",
}

_EXTRACT_ODDS_TABLE_JS = """() => {
    const table = document.querySelector('table');
    if (!table) return [];
    return Array.from(table.querySelectorAll('tbody tr')).map(row => {
        const cells = row.querySelectorAll('td');
        if (cells.length < 4) return null;
        const nameEl = cells[0].querySelector('p');
        return {
            bookmaker: (nameEl ? nameEl.textContent : cells[0].textContent).trim(),
            odds: [cells[1].textContent.trim(), cells[2].textContent.trim(), cells[3].textContent.trim()],
        };
    }).filter(Boolean);
}"""


class CuotasAhoraProvider(OddsProvider):
    """Scraper por DOM (Playwright) de cuotasahora.com (versión española de
    OddsPortal): comparador que agrega cuotas de muchas casas en una sola
    tabla por partido, en vez de una casa por sitio.

    Verificado en vivo: página de liga (.../laliga-ea-sports/) sin bloqueo
    anti-bot, solo dos gates estándar de UI a aceptar una vez por sesión de
    navegador (verificación de edad 18+ y el banner de cookies OneTrust,
    igual que en Betfair). Cada partido tiene su propia página
    (/football/h2h/equipo-a/equipo-b/) con una única <table> HTML (no CSS
    modules ni clases con hash) listando cuota 1/X/2 por casa.

    Su propia API de datos (proxy/ajax-nextgames-odds/...) devuelve la
    respuesta cifrada a propósito (base64 de contenido encriptado) para
    dificultar el scraping de la API - por eso se lee el DOM ya renderizado
    (la propia página lo descifra en el navegador para mostrarlo), igual que
    con el resto de proveedores, en vez de intentar romper ese cifrado.
    """

    name = "cuotasahora"

    def __init__(self, league_urls: dict[str, str] | None = None):
        self.league_urls = league_urls or DEFAULT_LEAGUE_URLS

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for sport in sports:
                url = self.league_urls.get(sport)
                if not url:
                    continue
                match_urls = await self._collect_match_urls(page, url)
                for match_url in match_urls:
                    market = await self._fetch_match(page, match_url, sport)
                    if market is not None:
                        markets.append(market)
            await browser.close()
        return markets

    async def _dismiss_gates(self, page) -> None:
        for selector in ("text=Soy mayor de 18", "#onetrust-reject-all-handler"):
            try:
                await page.click(selector, timeout=3000)
            except Exception:
                pass

    async def _collect_match_urls(self, page, league_url: str) -> list[str]:
        await page.goto(league_url, timeout=20000)
        await page.wait_for_timeout(1200)
        await self._dismiss_gates(page)
        await page.wait_for_timeout(800)
        hrefs = await page.eval_on_selector_all(
            'a[href*="/football/h2h/"]', "els => els.map(e => e.getAttribute('href'))"
        )
        seen = set()
        urls = []
        for href in hrefs:
            if not href:
                continue
            absolute = urllib.parse.urljoin(league_url, href)
            key = absolute.split("#")[0]
            if key in seen:
                continue
            seen.add(key)
            urls.append(absolute)
        return urls

    async def _fetch_match(self, page, match_url: str, sport: str) -> Market | None:
        try:
            await page.goto(match_url, timeout=20000)
            await page.wait_for_selector("table", timeout=15000)
            await page.wait_for_timeout(1500)

            body_text = await page.inner_text("body")
            if "Resultado final" in body_text:
                return None  # partido ya jugado, no sirve para arbitraje en vivo

            teams = await page.eval_on_selector_all(
                "a.min-w-0.self-center.truncate", "els => els.map(e => e.textContent.trim())"
            )
            if len(teams) < 2:
                return None

            raw_rows = await page.evaluate(_EXTRACT_ODDS_TABLE_JS)
        except Exception:
            return None

        return self._parse_match(teams[0], teams[1], raw_rows, sport)

    def _parse_match(self, home: str, away: str, raw_rows: list[dict], sport: str) -> Market | None:
        outcomes = []
        for row in raw_rows:
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row.get("bookmaker", "").strip().lower())
            if bookmaker_key is None:
                continue
            odds = row.get("odds", [])
            if len(odds) < 3:
                continue
            try:
                values = [float(o) for o in odds[:3]]
            except ValueError:
                continue
            outcomes.extend(
                [
                    Outcome(name="1", bookmaker=bookmaker_key, odds=values[0]),
                    Outcome(name="X", bookmaker=bookmaker_key, odds=values[1]),
                    Outcome(name="2", bookmaker=bookmaker_key, odds=values[2]),
                ]
            )
        if not outcomes:
            return None
        event_name = f"{home} vs. {away}"
        return Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes)
