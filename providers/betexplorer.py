import asyncio
import logging
import re
import urllib.parse

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

logger = logging.getLogger(__name__)

# Arranque deliberadamente pequeño (mismo criterio que cuotasahora.py en su
# primera versión): LaLiga y Champions League, verificadas en vivo el
# 2026-09-17. Ampliar aquí una vez este proveedor esté probado y estable en
# producción, no de golpe.
DEFAULT_LEAGUE_URLS = {
    "futbol": "https://www.betexplorer.com/football/spain/laliga/",
    "futbol_champions": "https://www.betexplorer.com/football/europe/champions-league/",
}

# Mismo criterio que providers/cuotasahora.py (ver ese fichero para el porqué
# de cada exclusión): estas son las casas con licencia DGOJ vigente que
# BetExplorer agrega y que no scrapeamos ya en directo por otra vía. Nombres
# verificados en vivo el 2026-09-17 contra una tabla real de BetExplorer -
# coinciden carácter a carácter con los de CuotasAhora, así que se reutiliza
# la misma clave normalizada para que ambos proveedores puedan fusionarse en
# el motor de arbitraje sin duplicar la misma casa con dos nombres distintos.
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

# Pestañas de tabla plana (un resultado por casa, sin líneas). La clave es el
# código interno que usa el JS del sitio para cambiar de pestaña
# (`match_change_tab(matchId, code, ...)`, ver _switch_tab) en vez del texto
# visible: el texto de BTTS ("Both Teams To Score") falló en vivo con
# Playwright headless (timeout esperando el enlace por texto, aunque
# funcionaba clicando a mano en el navegador) - probablemente por un layout
# de pestañas distinto según el ancho de viewport (las clases CSS de estas
# pestañas incluyen "Mobile" en el nombre, sugiriendo una barra responsive
# con variantes). El código interno del `onclick` no depende del texto
# visible ni del layout, así que es más fiable. Los nombres de resultado que
# trae cada tabla ("1"/"X"/"2", "Yes"/"No", "1X"/"12"/"X2") coinciden
# exactamente con los que ya usa cuotasahora.py.
EXTRA_MARKET_TABS: dict[str, str] = {
    "ha": "DNB",
    "dc": "DC",
    "bts": "BTTS",
}

# Pestañas con varias líneas (una tabla por línea, p.ej. "Total 2.5" o
# "Handicap -1"), a diferencia de cuotasahora.py: aquí el sitio ya renderiza
# TODAS las líneas de golpe en el DOM (con id="sortable-N"), así que no hace
# falta la lógica de acordeón con tope de líneas (ACCORDION_MAX_LINES) que sí
# necesita CuotasAhora - se leen todas sin clics extra.
LINE_MARKET_TABS: dict[str, str] = {
    "ou": "OU",
    # Hándicap asiático (verificado en vivo 2026-09-17): mismas tablas por
    # línea con cabecera ["Handicap", "1", "2"]. Incluye líneas partidas
    # ("-2, -2.5"), que _parse_line_table normaliza a "-2/-2.5".
    "ah": "AH",
}

_EXTRACT_ODDS_TABLES_JS = """
() => {
  const tables = Array.from(document.querySelectorAll('table[id^="sortable"]'));
  return tables.map(t => {
    const headers = Array.from(t.querySelectorAll('thead th'))
      .map(th => th.textContent.trim())
      .filter(Boolean);
    const rows = Array.from(t.querySelectorAll('tbody tr')).map(tr =>
      Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim()).filter(Boolean)
    );
    return { headers, rows };
  }).filter(t => t.rows.length > 0);
}
"""


class BetExplorerProvider(OddsProvider):
    """Scraper por DOM (Playwright) de betexplorer.com: comparador de cuotas
    independiente de CuotasAhora/OddsPortal (empresa distinta), verificado en
    vivo el 2026-09-17 como segunda fuente real, no teórica.

    A diferencia de cuotasahora.com (que renderiza sus tablas con divs
    propios sin `<table>` semántico), aquí cada pestaña de mercado es una
    `<table>` HTML normal con `<thead>`/`<tbody>`, lo que simplifica bastante
    el parseo. Página de partido con patrón fijo
    `/football/<país>/<liga>/<equipo-a>-<equipo-b>/<id>/`; el nombre de los
    equipos se lee del `<title>` ("Equipo A - Equipo B - H2H stats, odds"),
    igual que en cuotasahora.py, en vez de un `<h1>` (aquí el `<h1>` real
    pertenece al diálogo oculto de verificación de edad, no al partido).

    Partido ya empezado/finalizado: el elemento `.list-details__item__score`
    trae dígitos reales ("1:2") en vez de un ":" vacío. La fecha/hora de
    inicio NO sirve como señal para esto (sigue apareciendo en la página
    incluso con el partido ya en juego, verificado en vivo con un partido en
    el minuto 73 que todavía mostraba su fecha de inicio en otra parte de la
    página).

    Mismas casas DGOJ que cuotasahora.py (ver ALLOWED_BOOKMAKERS) y misma
    convención de nombres de resultado ("1"/"X"/"2", "Yes"/"No", etc.),
    verificada carácter a carácter en vivo, para que ambos proveedores puedan
    fusionarse correctamente en el motor de arbitraje cuando cubren el mismo
    partido (p.ej. LaLiga, donde `engine/team_aliases.py` ya tiene los 20
    equipos curados). En competiciones sin alias curados (de momento solo
    Champions League aquí) el cruce de eventos cae al respaldo de similitud
    de texto genérica de `engine/matching.py` (umbral alto, 0.85, pensado
    para minimizar falsos positivos) - el mismo riesgo que ya asume
    CuotasAhora en solitario para esa competición, no uno nuevo introducido
    por este proveedor.
    """

    name = "betexplorer"

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
                sport = sport_key.split("_", 1)[0]
                match_urls = await self._collect_match_urls(page, url)
                if not match_urls:
                    logger.warning(
                        "BetExplorer: 0 partidos encontrados en %s (title=%r) - "
                        "puede que el gate de edad/cookies no se haya cerrado o la web esté bloqueando el runner",
                        url,
                        await page.title(),
                    )
                for match_url in match_urls:
                    markets.extend(await self._fetch_match(page, match_url, sport))
            await browser.close()
        return markets

    async def _dismiss_gates(self, page) -> None:
        for selector in ("#ageYes", "#onetrust-reject-all-handler", "text=Reject All"):
            try:
                await page.click(selector, timeout=3000)
            except Exception:
                pass

    async def _collect_match_urls(self, page, league_url: str) -> list[str]:
        await page.goto(league_url, timeout=20000)
        await page.wait_for_timeout(1200)
        await self._dismiss_gates(page)
        await page.wait_for_timeout(800)
        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")

        league_path = urllib.parse.urlparse(league_url).path.rstrip("/")
        # Exactamente dos segmentos más que la propia liga (equipo-a-equipo-b/
        # id/): evita colar subpáginas de la liga como "/fixtures/" o
        # "/results/" (que solo añaden un segmento) - visto en vivo como
        # falso positivo antes de anclar el patrón así.
        pattern = re.compile(r"^" + re.escape(league_path) + r"/[a-z0-9-]+/[A-Za-z0-9]{6,12}/?$")
        seen = set()
        urls = []
        for href in hrefs:
            if not href:
                continue
            path = urllib.parse.urlparse(href).path
            if not pattern.match(path):
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
            await page.wait_for_timeout(1200)

            # Partido pendiente de empezar: el elemento de marcador
            # (.list-details__item__score) muestra solo ":" sin dígitos. La
            # fecha/hora de inicio ("18.09.2026 - 21:00") NO sirve como señal
            # porque sigue apareciendo en la página incluso con el partido ya
            # en juego (visto en vivo: un partido en el minuto 73 seguía
            # mostrando su fecha de inicio en otra parte de la página) - de
            # ahí el bug real que este chequeo reemplaza.
            score_text = await page.inner_text(".list-details__item__score")
            if any(ch.isdigit() for ch in score_text):
                return []

            title = await page.title()
            match = re.match(r"^(.+?) - (.+?) - H2H stats, odds$", title)
            if not match:
                return []
            home, away = match.group(1).strip(), match.group(2).strip()

            tables = await page.evaluate(_EXTRACT_ODDS_TABLES_JS)
        except Exception:
            logger.warning("BetExplorer: fallo cargando partido %s", match_url, exc_info=True)
            return []

        markets = []
        if tables:
            market = self._parse_flat_table(home, away, tables[0], "1X2", sport)
            if market is not None:
                markets.append(market)

        for tab_label, market_type in EXTRA_MARKET_TABS.items():
            table_data = await self._switch_tab(page, tab_label)
            if table_data is not None:
                market = self._parse_flat_table(home, away, table_data, market_type, sport)
                if market is not None:
                    markets.append(market)

        for tab_label, market_prefix in LINE_MARKET_TABS.items():
            markets.extend(await self._fetch_line_market(page, home, away, sport, tab_label, market_prefix))

        return markets

    async def _switch_tab(self, page, tab_code: str) -> dict | None:
        try:
            await page.click(f"a[onclick*=\"'{tab_code}',\"]", timeout=5000)
            await page.wait_for_timeout(1200)
            tables = await page.evaluate(_EXTRACT_ODDS_TABLES_JS)
            return tables[0] if tables else None
        except Exception:
            logger.warning("BetExplorer: fallo cambiando a la pestaña %r", tab_code, exc_info=True)
            return None

    async def _fetch_line_market(
        self, page, home: str, away: str, sport: str, tab_code: str, market_prefix: str
    ) -> list[Market]:
        try:
            await page.click(f"a[onclick*=\"'{tab_code}',\"]", timeout=5000)
            await page.wait_for_timeout(1200)
            tables = await page.evaluate(_EXTRACT_ODDS_TABLES_JS)
        except Exception:
            logger.warning("BetExplorer: fallo cambiando a la pestaña %r", tab_code, exc_info=True)
            return []

        markets = []
        for table_data in tables:
            market = self._parse_line_table(home, away, table_data, sport, market_prefix)
            if market is not None:
                markets.append(market)
        return markets

    def _parse_flat_table(self, home: str, away: str, table_data: dict, market_type: str, sport: str) -> Market | None:
        headers = table_data.get("headers", [])
        if not headers:
            return None
        outcomes = []
        for row in table_data.get("rows", []):
            if not row:
                continue
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row[0].strip().lower())
            if bookmaker_key is None:
                continue
            odds = row[1:]
            if len(odds) != len(headers):
                continue
            try:
                values = [float(o) for o in odds]
            except ValueError:
                continue
            outcomes.extend(
                Outcome(name=name, bookmaker=bookmaker_key, odds=value) for name, value in zip(headers, values)
            )
        if not outcomes:
            return None
        return Market(event=f"{home} vs. {away}", sport=sport, market_type=market_type, outcomes=outcomes)

    def _parse_line_table(self, home: str, away: str, table_data: dict, sport: str, market_prefix: str) -> Market | None:
        # Cabecera: ["Total"/"Handicap", <resultado 1>, <resultado 2>, ...] -
        # la primera columna es la línea (igual para toda la tabla), no un
        # resultado en sí.
        headers = table_data.get("headers", [])
        if len(headers) < 3 or headers[0] not in ("Total", "Handicap"):
            return None
        outcome_names = headers[1:]
        outcomes = []
        line = None
        for row in table_data.get("rows", []):
            if len(row) < 2:
                continue
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row[0].strip().lower())
            if bookmaker_key is None:
                continue
            # Una tabla es una única línea; si alguna fila trajera otra
            # distinta se ignora en vez de mezclar líneas en un mismo Market
            # (mezclar líneas produciría arbitrajes falsos).
            if line is not None and row[1] != line:
                continue
            line = row[1]
            odds = row[2:]
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
        if not outcomes or line is None:
            return None
        # Las líneas partidas ("-0.5, -1") son válidas pero tienen coma y
        # espacio - se normalizan con "/" ("-0.5/-1") para que el market_type
        # quede como una única palabra sin romper el resto del pipeline
        # (claves de dict, logs) y sin ambigüedad con el signo negativo.
        normalized_line = line.replace(", ", "/").replace(" ", "")
        market_type = f"{market_prefix}_{normalized_line}"
        return Market(event=f"{home} vs. {away}", sport=sport, market_type=market_type, outcomes=outcomes)
