import asyncio
import logging

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.altenar import _fmt_line
from providers.base import OddsProvider

logger = logging.getLogger(__name__)

SITE_ORIGIN = "https://www.sportium.es"
DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.sportium.es/apuestas/sports/soccer/competitions/45211/matches",
}
DEFAULT_EXTRA_MARKETS_MAX_MATCHES = 25
DEFAULT_EXTRA_MARKETS_CONCURRENCY = 6

# Mercados adicionales del mismo desplegable .ta-DropdownControl que ya usa "Goles
# Totales" (ta-item-GolesTotales): misma estructura simple que 1X2 (un botón de cuota
# por resultado, sin línea que emparejar), verificado en vivo el 2026-09-22.
# item de clase ta-item-<X> -> (market_type, código interno ta-MarketType-<Y> del
# bloque de ese mercado, nombres de resultado en el orden en que Sportium pinta los
# botones). El código interno hace falta porque "Goles Totales" (HCTG) se queda como
# columna secundaria pegada aunque el desplegable seleccione otro mercado (comprobado
# en vivo: sin este filtro, sus botones se colaban al final de cada evento).
SIMPLE_MARKETS: dict[str, tuple[str, str, list[str]]] = {
    "DobleOportunidad": ("DC", "DBLC", ["1X", "12", "X2"]),
    "AmbosMarcan": ("BTTS", "BTSC", ["Yes", "No"]),
    "Resultadoaldescanso": ("1X2_HT", "H1RS", ["1", "X", "2"]),
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
            current = { teams, odds: [], href: el.getAttribute('href') };
            events.push(current);
        } else if (current) {
            current.odds.push(el.textContent.trim());
        }
    }
    return events;
}"""

# Ficha de partido (no el listado): cada mercado es un bloque .ta-Market con
# su código interno ta-MarketType-<X> (mismos códigos que SIMPLE_MARKETS,
# verificado en vivo el 2026-09-25) y sus .ta-SelectionButtonView. Los de
# hándicap (asiático de 2 vías) llevan además .ta-infoTextHandicap con la
# línea, igual que "Goles Totales" en el listado; el resto (Doble Oportunidad,
# Empate No Cuenta, Ambos Marcan al descanso) solo llevan la cuota en
# .ta-price_text, sin línea que emparejar - misma estructura que
# SIMPLE_MARKETS, el orden de los botones determina el resultado.
_EXTRACT_MATCH_MARKETS_JS = """() => {
    const blocks = document.querySelectorAll('.ta-Market');
    return Array.from(blocks).map(block => {
        const codeClass = Array.from(block.classList).find(c => c.startsWith('ta-MarketType-'));
        const code = codeClass ? codeClass.replace('ta-MarketType-', '') : null;
        const buttons = Array.from(block.querySelectorAll('.ta-SelectionButtonView')).map(b => {
            const line = b.querySelector('.ta-infoTextHandicap');
            const price = b.querySelector('.ta-price_text');
            return {
                line: line ? line.textContent.trim() : null,
                price: price ? price.textContent.trim() : null,
            };
        });
        return { code, buttons };
    });
}"""

# Como _EXTRACT_EVENTS_JS pero solo con los botones del bloque .ta-Market cuyo
# ta-MarketType-<X> coincide con el mercado pedido (ver SIMPLE_MARKETS): necesario
# porque "Goles Totales" se queda como columna pegada junto a la seleccionada en el
# desplegable, y coger todos los .ta-SelectionButtonView del evento mezclaría ambas.
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

# Mercados de la ficha de partido: código ta-MarketType-<X> -> market_type de
# hándicap asiático de 2 vías. Verificado en vivo el 2026-09-25 en la pestaña
# "Handicap" (6 mercados: estos 3 más otros 3 de hándicap a 3 vías con empate,
# mismo patrón ya rechazado en Zebet/Versus/888sport/William Hill/PokerStars -
# quinta... sexta vez que aparece, así que no se implementan). Cada bloque
# tiene 2 botones en el mismo orden que el equipo local/visitante (igual que
# el resto del archivo): línea+cuota del local, línea+cuota del visitante.
_MATCH_HANDICAP_CODES: dict[str, str] = {
    "FAHC": "AH",
    "FAHT": "AH_HT",
    "H2OF": "AH_2H",
}
# Igual que SIMPLE_MARKETS pero de la ficha de partido en vez del desplegable
# del listado: sin línea que emparejar, el orden de los botones determina el
# resultado. Verificado en vivo en la pestaña "Mitades" (solo se leen los
# mercados que ya vienen expandidos sin clic adicional; el resto de los "49"
# necesitaría un clic por mercado individual, más caro, dejado para otra
# sesión).
_MATCH_SIMPLE_CODES: dict[str, tuple[str, list[str]]] = {
    "1DBC": ("DC_HT", ["1X", "12", "X2"]),
    "1DNB": ("DNB_HT", ["1", "2"]),
    "BTS1": ("BTTS_HT", ["Yes", "No"]),
}
# Más/Menos de la 1ª parte, misma estructura de línea+cuota que "Goles
# Totales" del listado (ver _EXTRACT_OU_EVENTS_JS), pero con varias líneas a
# la vez en distintos bloques .ta-Market con el mismo código.
_MATCH_OU_CODES: dict[str, str] = {
    "OUH1": "OU_HT",
}
# Pestañas de la ficha de partido a leer. Se clican por TEXTO ("Handicap (6)",
# el número entre paréntesis varía, de ahí el regex de prefijo), no por clase:
# probado en vivo el 2026-09-25 que la ficha de partido tiene DOS variantes de
# UI con clases distintas para los botones de pestaña (`ta-<eventId>-hcp_s`
# en una sesión interactiva de navegador, `ta-ButtonBarItem` genérico sin
# identificador de evento en Playwright headless real) - la lección ya
# conocida en este proyecto de "el panel interactivo no es prueba de lo que
# hará headless" aplicada aquí; el texto del botón es estable en ambas
# variantes y no requiere saber cuál le tocó a esta sesión. "Todos"/"Combos"/
# "Especiales" no se leen: la mayoría de sus mercados no vienen expandidos
# por defecto (exigirían un clic por mercado).
_MATCH_TABS = ("Handicap", "Mitades")


def parse_match_markets(raw_blocks: list[dict], home: str, away: str, sport: str, bookmaker: str) -> list[Market]:
    """Convierte los bloques de `_EXTRACT_MATCH_MARKETS_JS` (de una o varias
    pestañas de la ficha de partido) en los mercados nuevos: hándicap asiático
    de 2 vías, Doble Oportunidad/Empate No Cuenta/Ambos Marcan al descanso y
    Más/Menos al descanso. Un bloque cuyo código no está en ninguna de las 3
    tablas de arriba se ignora (mercado sin implementar, no se adivina)."""
    event_name = f"{home} vs. {away}"
    found: dict[str, Market] = {}
    for block in raw_blocks:
        code = block.get("code")
        buttons = block.get("buttons") or []
        market = None
        if code in _MATCH_HANDICAP_CODES:
            market = _parse_handicap_block(buttons, _MATCH_HANDICAP_CODES[code], event_name, sport, bookmaker)
        elif code in _MATCH_SIMPLE_CODES:
            market_type, outcome_names = _MATCH_SIMPLE_CODES[code]
            market = _parse_simple_block(buttons, market_type, outcome_names, event_name, sport, bookmaker)
        elif code in _MATCH_OU_CODES:
            market = _parse_ou_block(buttons, _MATCH_OU_CODES[code], event_name, sport, bookmaker)
        if market is not None and market.market_type not in found:
            found[market.market_type] = market
    return list(found.values())


def _parse_handicap_block(buttons: list[dict], prefix: str, event_name: str, sport: str, bookmaker: str) -> Market | None:
    if len(buttons) != 2:
        return None
    try:
        home_line, home_odds = float(buttons[0]["line"]), float(buttons[0]["price"])
        away_line, away_odds = float(buttons[1]["line"]), float(buttons[1]["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if home_line != -away_line:
        return None  # no es un hándicap simétrico de 2 vías: no se adivina
    market_type = f"{prefix}_{_fmt_line(home_line, signed=True)}"
    return Market(
        event=event_name, sport=sport, market_type=market_type,
        outcomes=[Outcome(name="1", bookmaker=bookmaker, odds=home_odds), Outcome(name="2", bookmaker=bookmaker, odds=away_odds)],
    )


def _parse_simple_block(
    buttons: list[dict], market_type: str, outcome_names: list[str], event_name: str, sport: str, bookmaker: str
) -> Market | None:
    if len(buttons) != len(outcome_names):
        return None
    try:
        outcomes = [Outcome(name=name, bookmaker=bookmaker, odds=float(b["price"])) for name, b in zip(outcome_names, buttons)]
    except (KeyError, TypeError, ValueError):
        return None
    return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)


def _parse_ou_block(buttons: list[dict], prefix: str, event_name: str, sport: str, bookmaker: str) -> Market | None:
    if len(buttons) != 2:
        return None
    line = buttons[0].get("line")
    if not line or buttons[1].get("line") != line:
        return None
    try:
        outcomes = [
            Outcome(name="Over", bookmaker=bookmaker, odds=float(buttons[0]["price"])),
            Outcome(name="Under", bookmaker=bookmaker, odds=float(buttons[1]["price"])),
        ]
    except (TypeError, ValueError):
        return None
    return Market(event=event_name, sport=sport, market_type=f"{prefix}_{line}", outcomes=outcomes)


class SportiumProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Sportium: no expone una API de cuotas
    limpia (probablemente WebSocket), así que se lee la tabla ya renderizada.

    Verificado en vivo: contenedor .ta-EventListGroup, cada evento es un
    .ta-EventListItemDetails con equipos en .ta-ParticipantItem, seguido en el
    DOM por sus botones de cuota .ta-SelectionButtonView (1, X, 2, ...).

    Implementa 1X2, Goles Totales (over/under), Doble Oportunidad, Ambos Marcan
    (BTTS) y Resultado al descanso (1X2_HT). El mercado se cambia con el
    desplegable .ta-DropdownControl -> opción .ta-item-<X> (misma página, sin
    recargar); los cuatro mercados nuevos comparten desplegable con "Goles
    Totales" (ver SIMPLE_MARKETS), verificado en vivo el 2026-09-22. La línea de
    goles la decide Sportium por partido (normalmente 2.5, pero no siempre,
    p.ej. 4.5 en un partido muy desigual), así que el market_type incluye la
    línea ("OU_2.5", "OU_4.5", ...) para no comparar cuotas de líneas distintas
    entre casas.

    **Ampliado 2026-09-25**: además del listado, lee las pestañas "Handicap" y
    "Mitades" de la ficha de cada partido (ver `_MATCH_TABS`/`parse_match_markets`)
    para un número acotado de partidos (`extra_markets_max_matches`, sin
    horizonte porque el listado no da fecha exacta) — añade hándicap asiático
    de 2 vías (partido/1ª/2ª parte), Doble Oportunidad/Empate No
    Cuenta/Ambos Marcan al descanso y Más/Menos al descanso. Cada pestaña
    exige un clic (no cambia la URL, a diferencia de PokerStars), así que es
    una página de Playwright + 2 clics por partido, mismo orden de coste que
    PokerStars.
    """

    name = "sportium"

    def __init__(
        self,
        competition_urls: dict[str, str] | None = None,
        extra_markets_max_matches: int = DEFAULT_EXTRA_MARKETS_MAX_MATCHES,
        extra_markets_concurrency: int = DEFAULT_EXTRA_MARKETS_CONCURRENCY,
    ):
        self.competition_urls = competition_urls or DEFAULT_COMPETITION_URLS
        self.extra_markets_max_matches = extra_markets_max_matches
        self.extra_markets_concurrency = extra_markets_concurrency

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
                raw_1x2_events = await page.eval_on_selector(".ta-EventListGroup", _EXTRACT_EVENTS_JS)
                markets.extend(self._parse_events(raw_1x2_events, sport))

                markets.extend(await self._fetch_over_under(page, sport))

                for item_class, (market_type, code, outcome_names) in SIMPLE_MARKETS.items():
                    raw_events = await self._fetch_simple_market(page, item_class, code)
                    markets.extend(self._parse_simple_market(raw_events, sport, market_type, outcome_names))

                matches = self._matches_with_href(raw_1x2_events)[: self.extra_markets_max_matches]
                markets.extend(await self._fetch_match_extra_markets(browser, matches, sport))
            await browser.close()
        return markets

    @staticmethod
    def _matches_with_href(raw_events: list[dict]) -> list[tuple[str, str, str]]:
        matches = []
        for event in raw_events:
            teams = event.get("teams", [])
            href = event.get("href")
            if len(teams) == 2 and href:
                matches.append((teams[0], teams[1], href))
        return matches

    async def _fetch_match_extra_markets(self, browser, matches: list[tuple[str, str, str]], sport: str) -> list[Market]:
        """Hándicap/Mitades de la ficha de cada partido en `matches` (ver
        `parse_match_markets`), en paralelo con concurrencia acotada. Un
        fallo en una pestaña o un partido suelto no descarta el resto, igual
        que el resto de proveedores concurrentes de este repo."""
        if not matches:
            return []
        semaphore = asyncio.Semaphore(self.extra_markets_concurrency)

        async def fetch_one(home: str, away: str, href: str) -> list[Market]:
            async with semaphore:
                page = await browser.new_page()
                try:
                    await page.goto(f"{SITE_ORIGIN}{href}", timeout=20000, wait_until="domcontentloaded")
                    # Las pestañas de categoría (Handicap/Mitades) tardan más en
                    # pintarse que el resto de la ficha (verificado en vivo: a
                    # veces 3-4s) - un timeout de click corto las confunde con un
                    # partido sin esas pestañas.
                    await page.wait_for_selector("text=/^Handicap/", timeout=15000)
                    raw_blocks: list[dict] = []
                    for tab in _MATCH_TABS:
                        try:
                            await page.click(f"text=/^{tab}/", timeout=10000)
                            await page.wait_for_timeout(600)
                            raw_blocks.extend(await page.evaluate(_EXTRACT_MATCH_MARKETS_JS))
                        except Exception:
                            logger.warning("Sportium: fallo leyendo pestaña %s de %s", tab, href, exc_info=True)
                    return parse_match_markets(raw_blocks, home, away, sport, self.name)
                except Exception:
                    logger.warning("Sportium: fallo leyendo ficha %s", href, exc_info=True)
                    return []
                finally:
                    await page.close()

        results = await asyncio.gather(*[fetch_one(home, away, href) for home, away, href in matches])
        markets = [market for sub in results for market in sub]
        logger.info("Sportium: %d mercados nuevos (AH/DC_HT/DNB_HT/BTTS_HT/OU_HT) en %d partidos", len(markets), len(matches))
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
