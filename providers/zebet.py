"""Zebet (`providers/zebet.py`), scraper por DOM (Playwright).

Plataforma propia del grupo Zeturf (no un B2B conocido como Kambi/Altenar/Digitain:
la home enlaza el logo de Zeturf y no hay ninguna llamada de red a un dominio de
plataforma de terceros durante la carga, ver README). Licencia DGOJ: ZEBETTING Y
GAMING (ya confirmada en `checklist.md`, scraping directo pendiente hasta ahora).

**Verificado en vivo el 2026-09-24 con `chromium.launch(headless=True)` real** (no
solo el Browser pane, que había dejado esta casa como "sin confirmar" en el
checklist anterior por la misma razón que Interwetten/Retabet/OlyBet: el navegador
interactivo no basta como señal): carga completa, sin Cloudflare/CAPTCHA/WAF, con
las cuotas ya en el HTML servido (no hace falta esperar la conexión SSE a
`sse.zebet.es`, que solo empuja actualizaciones de partidos EN VIVO vía el
protocolo Mercure - las cuotas pre-partido vienen renderizadas del lado del
servidor, igual que Sportium/Marca Apuestas/PokerStars).

Estructura del DOM (página de competición, p.ej.
`https://www.zebet.es/es/competition/306-laliga`), verificada en vivo:

- Los partidos viven dentro de `#event`, bajo un acordeón titulado "Próximos
  partidos" - no se ha visto ningún indicador de partido en directo mezclado en
  esta lista (el widget de "en vivo" de la portada es una sección aparte).
- Cada partido es un `.item-content.catcomp` con:
  - equipos: un único `div.uk-visible-small.uk-text-truncate` con el texto
    "Equipo1 / Equipo2" (separados por " / ", sin acentos raros ni abreviaturas
    vistas en las pruebas).
  - cuotas 1X2: `.bet-actor1` / `.bet-actorN` / `.bet-actor2` identifican
    local/empate/visitante por **clase**, no por el texto que muestran (la casa
    duplica cada cuota en dos variantes responsive, `-hidden-small` y
    `-visible-small`, con el mismo valor pero distinta etiqueta - "Málaga" en una,
    "1" en la otra -, así que se lee solo la variante `.uk-visible-small` para no
    duplicar). Cada una lleva un `.pmq-cote` con la cuota en coma decimal española
    ("3,75").
- Hora del partido en `.bet-time` como "DD/MM HH:MM" sin año: se deja
  `Market.start_time` en `None`, igual que `providers/sportium.py` y
  `providers/pokerstars.py` (sin horizonte propio - se lee lo que muestre el
  listado "Próximos partidos", que ya son solo eventos futuros).
- Cookie consent de Cookiebot: hay que aceptarlo una vez por sesión de navegador o
  el acordeón de partidos no termina de cargar; es un banner estándar (no un WAF),
  se acepta con un simple `page.click`.
- Solo 1X2 por ahora (mismo alcance inicial que tuvo Sportium). La página general
  `/apuestas-deportivas/futbol` (sin filtrar por competición) mostró además un
  segundo mercado por partido ("¿Más o menos de 2.5 goles en el 1o tiempo?"), pero
  no se ha visto en la vista por competición ni se ha explorado si es estable
  partido a partido - queda pendiente de una sesión futura.
"""

import asyncio

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.zebet.es/es/competition/306-laliga",
}

# La web manda esta cabecera; verificado en vivo el 2026-09-24 sin ningún reto
# anti-bot con ella (misma UA que usan ya providers/bet777.py y otros de este repo).
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

_COOKIE_ACCEPT_SELECTOR = "#CybotCookiebotDialogBodyButtonAccept"

# Ver docstring del módulo: local/empate/visitante se identifican por la clase
# bet-actor1/bet-actorN/bet-actor2, y se lee solo la variante ".uk-visible-small"
# para no coger dos veces la misma cuota (la casa la duplica para el layout
# responsive, con una etiqueta de texto distinta pero el mismo valor).
_EXTRACT_EVENTS_JS = """(container) => {
    const items = Array.from(container.querySelectorAll('.item-content.catcomp'));
    return items.map(item => {
        const nameEl = item.querySelector('.uk-visible-small.uk-text-truncate');
        const teams = nameEl ? nameEl.textContent.trim().split(' / ') : [];
        const odd = (cls) => {
            const el = item.querySelector('.' + cls + '.uk-visible-small .pmq-cote');
            return el ? el.textContent.trim() : null;
        };
        return { teams, odds: [odd('bet-actor1'), odd('bet-actorN'), odd('bet-actor2')] };
    });
}"""


class ZebetProvider(OddsProvider):
    """Zebet (grupo Zeturf): 1X2 pre-partido de LaLiga vía DOM, sin API ni
    autenticación. Ver docstring del módulo para el detalle verificado en vivo."""

    name = "zebet"

    def __init__(self, competition_urls: dict[str, str] | None = None):
        self.competition_urls = competition_urls or DEFAULT_COMPETITION_URLS

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            for sport in sports:
                url = self.competition_urls.get(sport)
                if not url:
                    continue
                await page.goto(url, timeout=20000, wait_until="load")
                try:
                    await page.click(_COOKIE_ACCEPT_SELECTOR, timeout=3000)
                except Exception:
                    pass  # ya aceptado en una sesión previa, o el banner no apareció
                await page.wait_for_selector("#event", timeout=20000)
                raw_events = await page.eval_on_selector("#event", _EXTRACT_EVENTS_JS)
                markets.extend(self._parse_events(raw_events, sport))
            await browser.close()
        return markets

    def _parse_events(self, raw_events: list[dict], sport: str) -> list[Market]:
        markets = []
        for event in raw_events:
            teams = event.get("teams", [])
            odds = [self._to_float(o) for o in event.get("odds", [])]
            if len(teams) != 2 or len(odds) != 3 or any(o is None for o in odds):
                continue
            outcomes = [
                Outcome(name="1", bookmaker=self.name, odds=odds[0]),
                Outcome(name="X", bookmaker=self.name, odds=odds[1]),
                Outcome(name="2", bookmaker=self.name, odds=odds[2]),
            ]
            event_name = f"{teams[0].strip()} vs. {teams[1].strip()}"
            markets.append(Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes))
        return markets

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        if not raw:
            return None
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError:
            return None
        return value if value > 1.0 else None
