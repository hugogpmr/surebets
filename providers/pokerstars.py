"""PokerStars Sports por DOM (Playwright): no hay API pública utilizable.

TSG Interactive Spain, S.A. (licencia DGOJ, ver checklist.md). Estaba marcada
"sin fuente" en README/checklist. Verificado en vivo el 2026-09-22:

- La página carga sin ningún reto visible (sin Cloudflare/reCAPTCHA en la
  navegación normal) y pinta un listado de partidos con 1X2 real en
  `https://www.pokerstars.es/sports/futbol/1/matches/` (117 partidos / 40
  competiciones en la comprobación en vivo).
- Por debajo hay una API JSON propia (`POST /sports/web/gbp/sca/graphql`,
  `POST /sports/web/markets-updates`) con pinta de tecnología Betfair (IDs de
  mercado con el formato clásico de Betfair Exchange, `eventTypeId=1` para
  fútbol como en Betfair) — pero **está detrás de Akamai Bot Manager**: un
  `fetch()` ejecutado a mano dentro de la misma página, con la misma sesión,
  devuelve 403 "Access Denied" de Akamai (`errors.edgesuite.net`), el mismo
  patrón exacto que ya bloqueaba a Kirolbet (`providers/kirolbet.py`) incluso
  con `fetch()` real. Por eso este proveedor lee el DOM ya renderizado (como
  Sportium/Betfair/Winamax) en vez de hablar esa API directamente.

Estructura verificada en vivo (atributos `data-testid`, no clases con hash,
así que son estables entre despliegues): cada bloque de competición tiene un
`[data-testid="market-template-header"]` con las cabeceras de columna
("...LocalEmpateVisitante" para 1X2) y un `[data-testid="event-list"]` con
`<li data-testid="event">` por partido: `[data-testid="event-participants"]`
con dos `<span>` hijos directos (equipo local, equipo visitante — el guión
separador va en un `<span>` anidado dentro del primero, no en el texto plano,
así que no hace falta partir un string) y tres
`[data-testid="selection"]` con la cuota (1, X, 2 en ese orden), en coma
decimal española.

Solo 1X2 por ahora (no se ha explorado el resto de mercados: cada uno abre su
propia página de partido, coste de otra sesión). Sin hora de inicio exacta en
el listado (solo "Hoy"/"Mañana"/día de la semana + hora, sin fecha completa),
así que `Market.start_time` se deja `None`, igual que en `providers/sportium.py`.
"""

import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

BOOKMAKER = "pokerstars"
DEFAULT_URL = "https://www.pokerstars.es/sports/futbol/1/matches/"

# Un event-list puede en teoría no ser 1X2 (no se ha visto en las ~40
# competiciones comprobadas en vivo, pero por si acaso): se valida el texto de
# su cabecera de mercado antes de leerlo, en vez de asumirlo.
_1X2_HEADER_WORDS = ("Local", "Empate", "Visitante")

_EXTRACT_JS = """() => {
    const lists = Array.from(document.querySelectorAll('[data-testid="event-list"]'));
    return lists.map(list => {
        let node = list, heading = null, marketHeader = null;
        for (let i = 0; i < 8 && node; i++) {
            if (!marketHeader) {
                const h = node.querySelector('[data-testid="market-template-header"]');
                if (h) marketHeader = h.textContent;
            }
            if (!heading) {
                const t = node.querySelector('h1,h2,h3,h4,[class*="title" i],[class*="heading" i]');
                if (t && t.textContent.trim()) heading = t.textContent.trim();
            }
            node = node.parentElement;
        }
        const events = Array.from(list.querySelectorAll('[data-testid="event"]')).map(li => {
            const participants = li.querySelector('[data-testid="event-participants"]');
            if (!participants || participants.children.length < 2) return null;
            const homeNode = participants.children[0].childNodes[0];
            const home = homeNode ? homeNode.textContent.trim() : '';
            const away = participants.children[1].textContent.trim();
            const odds = Array.from(li.querySelectorAll('[data-testid="selection"]'))
                .map(b => b.textContent.trim());
            return { home, away, odds };
        }).filter(Boolean);
        return { heading, marketHeader, events };
    });
}"""


def _parse_odds(raw: str) -> float | None:
    try:
        value = float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return None
    return value if value > 1.0 else None


class PokerStarsProvider(OddsProvider):
    """PokerStars Sports por DOM (ver docstring del módulo). Solo 1X2 de fútbol
    dentro del horizonte que la propia web decide mostrar en `/matches/`."""

    name = BOOKMAKER

    def __init__(
        self,
        url: str = DEFAULT_URL,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.url = url
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        return asyncio.run(self._fetch_markets_async())

    async def _fetch_markets_async(self) -> list[Market]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(self.url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_selector('[data-testid="event-list"]', timeout=20000)
                await page.wait_for_selector('[data-testid="selection"]', timeout=20000)
                raw_groups = await page.evaluate(_EXTRACT_JS)
            finally:
                await browser.close()
        return self._parse_groups(raw_groups)

    def _parse_groups(self, raw_groups: list[dict]) -> list[Market]:
        markets: list[Market] = []
        for group in raw_groups:
            header = group.get("marketHeader") or ""
            if not all(word in header for word in _1X2_HEADER_WORDS):
                continue  # no es un bloque 1X2 (mercado inesperado): se descarta, no se adivina
            heading = group.get("heading")
            for event in group.get("events", []):
                home, away = event.get("home"), event.get("away")
                odds = event.get("odds") or []
                if not home or not away or len(odds) != 3:
                    continue
                if is_excluded([heading, home, away], self.exclude_esports, self.exclude_women):
                    continue
                parsed = [_parse_odds(o) for o in odds]
                if any(value is None for value in parsed):
                    continue  # selección suspendida (sin cuota numérica) u otro formato inesperado
                outcomes = [
                    Outcome(name=name, bookmaker=self.name, odds=value)
                    for name, value in zip(("1", "X", "2"), parsed)
                ]
                markets.append(Market(event=f"{home} vs. {away}", sport="futbol", market_type="1X2", outcomes=outcomes))
        return markets
