import asyncio
import logging
import urllib.parse

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

logger = logging.getLogger(__name__)

DEFAULT_LEAGUE_URLS = {
    "futbol": "https://www.cuotasahora.com/football/spain/laliga-ea-sports/",
    "futbol_champions": "https://www.cuotasahora.com/football/europe/champions-league/",
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

# Pestañas de mercado adicionales a la 1X2 (que ya viene seleccionada por
# defecto al cargar la página del partido). Cada partido de CuotasAhora tiene
# más pestañas todavía (hándicap europeo, marcador correcto, descanso/final,
# resultado sin empate...) detrás de un desplegable "Más", pero estas dos son
# las más lucrativas para arbitraje verificadas en vivo el 2026-09-16: tabla
# plana igual que 1X2 (sin líneas/hándicaps que agrupar como en "Más/Menos
# de", que usa un acordeón por línea y necesitaría una extracción distinta).
# Clave = texto exacto del botón de pestaña, valor = market_type resultante.
EXTRA_MARKET_TABS: dict[str, str] = {
    "Ambos equipos marcan": "BTTS",
    "Doble oportunidad": "DC",
}

# Misma tabla HTML para cualquier pestaña (1X2, BTTS, Doble oportunidad):
# primera columna = casa, última columna = payout%, columnas del medio = una
# cuota por resultado. En vez de fijar los nombres de resultado a mano por
# mercado, se leen del <thead> (p.ej. ["Bookmakers","Yes","No","Payout"] para
# BTTS, ["Bookmakers","1X","12","X2","Payout"] para Doble oportunidad) -
# verificado en vivo el 2026-09-16 que la cabecera siempre coincide en número
# y orden con las columnas de cuota de cada fila.
_EXTRACT_ODDS_TABLE_JS = """() => {
    const table = document.querySelector('table');
    if (!table) return { headers: [], rows: [] };
    const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    const rows = Array.from(table.querySelectorAll('tbody tr')).map(row => {
        const cells = Array.from(row.querySelectorAll('td'));
        if (cells.length < 3) return null;
        const nameEl = cells[0].querySelector('p');
        return {
            bookmaker: (nameEl ? nameEl.textContent : cells[0].textContent).trim(),
            odds: cells.slice(1, -1).map(td => td.textContent.trim()),
        };
    }).filter(Boolean);
    return { headers, rows };
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
    modules ni clases con hash) listando cuota 1/X/2 por casa, más pestañas
    para otros mercados (ver EXTRA_MARKET_TABS) que reutilizan la misma
    tabla.

    Su propia API de datos (proxy/ajax-nextgames-odds/...) devuelve la
    respuesta cifrada a propósito (base64 de contenido encriptado) para
    dificultar el scraping de la API - por eso se lee el DOM ya renderizado
    (la propia página lo descifra en el navegador para mostrarlo), igual que
    con el resto de proveedores, en vez de intentar romper ese cifrado.

    `league_urls` acepta varias claves de competición por deporte (p.ej.
    "futbol" para LaLiga y "futbol_champions" para la Champions League): cada
    clave es un "sport" independiente de cara al motor de arbitraje, así que
    conviene pasar ambas en la lista `sports` del ciclo de escaneo si se
    quiere cobertura de las dos. Se mantienen en el mismo `sport="futbol"` en
    el Market resultante (ver `_fetch_match`) porque el motor no necesita
    distinguir competición, solo evento+mercado.
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
            for sport_key in sports:
                url = self.league_urls.get(sport_key)
                if not url:
                    continue
                # sport_key puede ser "futbol_champions" etc. (una clave de
                # competición distinta por URL), pero de cara al motor de
                # arbitraje todo esto es fútbol: se normaliza al deporte real
                # para poder cruzar eventos con el resto de proveedores.
                sport = sport_key.split("_", 1)[0]
                match_urls = await self._collect_match_urls(page, url)
                if not match_urls:
                    logger.warning(
                        "CuotasAhora: 0 partidos encontrados en %s (title=%r) - "
                        "puede que el gate de edad/cookies no se haya cerrado o la web esté bloqueando el runner",
                        url,
                        await page.title(),
                    )
                for match_url in match_urls:
                    markets.extend(await self._fetch_match(page, match_url, sport))
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

    async def _fetch_match(self, page, match_url: str, sport: str) -> list[Market]:
        try:
            await page.goto(match_url, timeout=20000)
            await page.wait_for_selector("table", timeout=15000)
            await page.wait_for_timeout(1500)

            body_text = await page.inner_text("body")
            if "Resultado final" in body_text:
                return []  # partido ya jugado, no sirve para arbitraje en vivo

            teams = await page.eval_on_selector_all(
                "a.min-w-0.self-center.truncate", "els => els.map(e => e.textContent.trim())"
            )
            if len(teams) < 2:
                return []

            table_data = await page.evaluate(_EXTRACT_ODDS_TABLE_JS)
        except Exception:
            logger.warning("CuotasAhora: fallo cargando partido %s", match_url, exc_info=True)
            return []

        markets = []
        market = self._parse_match(teams[0], teams[1], table_data, "1X2", sport)
        if market is not None:
            markets.append(market)
        elif table_data.get("rows"):
            logger.warning(
                "CuotasAhora: %s devolvió %d filas pero ninguna casó con ALLOWED_BOOKMAKERS/odds válidas: %r",
                match_url,
                len(table_data["rows"]),
                [r.get("bookmaker") for r in table_data["rows"]],
            )

        for tab_label, market_type in EXTRA_MARKET_TABS.items():
            extra_table_data = await self._switch_market_tab(page, tab_label)
            if extra_table_data is None:
                continue
            extra_market = self._parse_match(teams[0], teams[1], extra_table_data, market_type, sport)
            if extra_market is not None:
                markets.append(extra_market)

        return markets

    async def _switch_market_tab(self, page, tab_label: str) -> dict | None:
        try:
            await page.click(f'button:has-text("{tab_label}")', timeout=5000)
            return await self._read_table_when_stable(page)
        except Exception:
            logger.warning("CuotasAhora: fallo cambiando a la pestaña %r", tab_label, exc_info=True)
            return None

    async def _read_table_when_stable(self, page) -> dict:
        # Tras cambiar de pestaña, la cabecera se actualiza al instante pero
        # cada fila (casa) refresca su propia cuota de forma independiente y
        # con retardo variable - un wait_for_timeout(800) fijo a veces lee la
        # tabla a medio refrescar: la cabecera ya dice p.ej. "Yes"/"No" pero
        # alguna fila concreta (no siempre la misma) todavia arrastra el
        # numero de la pestaña anterior (1X2), coincidiendo por casualidad en
        # numero de columnas y coandolando un "margen" disparatado (~70%)
        # como si fuera una surebet real. Confirmado en vivo el 2026-09-16
        # contra cuotasahora.com: bet365/retabet mostraban en "Ambos equipos
        # marcan" los mismos valores que sus columnas "1"/"X" de la pestaña
        # 1X2. Se espera a que dos lecturas consecutivas coincidan para dar
        # la tabla por asentada, en vez de fiarse de un tiempo fijo.
        previous = None
        for _ in range(8):
            await page.wait_for_timeout(400)
            current = await page.evaluate(_EXTRACT_ODDS_TABLE_JS)
            if current == previous:
                return current
            previous = current
        return previous

    def _parse_match(
        self, home: str, away: str, table_data: dict, market_type: str, sport: str
    ) -> Market | None:
        headers = table_data.get("headers", [])
        # La cabecera es ["Bookmakers", <resultado 1>, ..., "Payout"]: los
        # nombres de resultado son todo lo que queda al quitar esas dos.
        outcome_names = headers[1:-1] if len(headers) >= 3 else []
        if not outcome_names:
            return None
        outcomes = []
        for row in table_data.get("rows", []):
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row.get("bookmaker", "").strip().lower())
            if bookmaker_key is None:
                continue
            odds = row.get("odds", [])
            if len(odds) != len(outcome_names):
                continue
            try:
                values = [float(o) for o in odds]
            except ValueError:
                continue
            outcomes.extend(
                Outcome(name=name, bookmaker=bookmaker_key, odds=value)
                for name, value in zip(outcome_names, values)
            )
        if not outcomes:
            return None
        event_name = f"{home} vs. {away}"
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)
