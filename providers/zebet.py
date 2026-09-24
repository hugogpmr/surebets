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

**Doble oportunidad, Ambos marcan y Par/Impar (añadido 2026-09-24)**: a diferencia
del 1X2 (que sale entero en el listado de competición), estos tres mercados solo
están en la **ficha de cada partido** (`/es/event/<slug>`, enlazada desde
`.bet-activebets a` de cada bloque del listado) - así que amplían el coste de un
ciclo: una navegación de página por partido además de la del listado (~20 páginas
para LaLiga completa), no una sola petición JSON como en otras casas de este repo.
Cada mercado es un bloque `[data-t="<código>"]` con un `.pmq-cote`/`.pmq-cote-acteur`
por resultado, identificado por su **texto de etiqueta** (no por clase, a
diferencia del 1X2 del listado):

- `data-t="Doble oportunidad"` - único en la página, resultados "1X"/"12"/"X2" ->
  `DC`.
- `data-t="¿Ambos equipos marcarán al menos un gol?"` - único, "Si"/"No" -> `BTTS`.
- `data-t="Par - Impar"` - **el mismo código se reutiliza para el partido completo,
  cada equipo por separado y cada mitad** (verificado en vivo en 2 partidos
  distintos): el bloque del partido completo se identifica por el texto exacto y
  estable "¿El número de goles marcados será par o impar?" (sin nombre de equipo
  interpolado, a diferencia de los otros); "Par"/"Impar" -> `OE`.
- El resto de los ~45 grupos de mercado de la ficha (hándicap con líneas en formato
  marcador "Hándicap (2:0)", más/menos con muchas líneas anidadas bajo el mismo
  `data-t` que su variante por mitad, combinadas, marcador exacto...) quedan fuera
  por ahora: piden más trabajo de desambiguación (líneas, mitades) que estos tres,
  que son bloques únicos y de resultado fijo. Candidatos para una próxima sesión.
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
# responsive, con una etiqueta de texto distinta pero el mismo valor). El enlace a
# la ficha del partido (para Doble oportunidad/Ambos marcan/Par-Impar) vive en
# ".bet-activebets a" del mismo bloque.
_EXTRACT_EVENTS_JS = """(container) => {
    const items = Array.from(container.querySelectorAll('.item-content.catcomp'));
    return items.map(item => {
        const nameEl = item.querySelector('.uk-visible-small.uk-text-truncate');
        const teams = nameEl ? nameEl.textContent.trim().split(' / ') : [];
        const odd = (cls) => {
            const el = item.querySelector('.' + cls + '.uk-visible-small .pmq-cote');
            return el ? el.textContent.trim() : null;
        };
        const linkEl = item.querySelector('.bet-activebets a[href*="/es/event/"]');
        return {
            teams,
            odds: [odd('bet-actor1'), odd('bet-actorN'), odd('bet-actor2')],
            href: linkEl ? linkEl.getAttribute('href') : null,
        };
    });
}"""

# Doble oportunidad y Ambos marcan son bloques únicos en la ficha del partido,
# identificados por su atributo data-t. Par-Impar reutiliza el mismo data-t para
# el partido completo, cada equipo y cada mitad (verificado en vivo en 2 partidos
# distintos): el del partido completo se distingue por su texto exacto y estable,
# sin nombre de equipo interpolado. Ver docstring del módulo.
_OE_FULL_MATCH_QUESTION = "¿El número de goles marcados será par o impar?"

_EXTRACT_MATCH_EXTRAS_JS = """(oeQuestion) => {
    function block(attr, question) {
        const els = Array.from(document.querySelectorAll('[data-t="' + attr + '"]'));
        const match = question
            ? els.find(el => el.textContent.replace(/\\s+/g, ' ').trim().startsWith(question))
            : els[0];
        if (!match) return null;
        const parent = match.closest('.item-content');
        if (!parent) return null;
        return {
            odds: Array.from(parent.querySelectorAll('.pmq-cote')).map(e => e.textContent.trim()),
            labels: Array.from(parent.querySelectorAll('.pmq-cote-acteur')).map(e => e.textContent.trim()),
        };
    }
    return {
        dc: block('Doble oportunidad'),
        btts: block('¿Ambos equipos marcarán al menos un gol?'),
        oe: block('Par - Impar', oeQuestion),
    };
}"""

# (market_type, {etiqueta de la web -> nombre de resultado}) por cada mercado extra.
# Mismos prefijos y nombres de resultado que Altenar/Kambi/Winamax/CuotasAhora, para
# que crucen.
_DC_LABELS = {"1X": "1X", "12": "12", "X2": "X2"}
_BTTS_LABELS = {"Si": "Yes", "No": "No"}
_OE_LABELS = {"Impar": "Odd", "Par": "Even"}
_EXTRA_MARKETS = {"dc": ("DC", _DC_LABELS), "btts": ("BTTS", _BTTS_LABELS), "oe": ("OE", _OE_LABELS)}


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
                events = self._parse_events(raw_events, sport)
                for event_name, market_1x2, href in events:
                    if market_1x2 is not None:
                        markets.append(market_1x2)
                    if href:
                        markets.extend(await self._fetch_match_extras(page, href, event_name, sport))
            await browser.close()
        return markets

    async def _fetch_match_extras(self, page, href: str, event_name: str, sport: str) -> list[Market]:
        """Doble oportunidad/Ambos marcan/Par-Impar viven solo en la ficha del
        partido (ver docstring del módulo): una navegación de página más por
        partido. Un partido con la ficha rota no debe tumbar a los demás."""
        try:
            await page.goto("https://www.zebet.es" + href, timeout=20000, wait_until="load")
            await page.wait_for_selector('[data-t="Doble oportunidad"]', timeout=8000)
            raw = await page.evaluate(_EXTRACT_MATCH_EXTRAS_JS, _OE_FULL_MATCH_QUESTION)
        except Exception:
            return []
        return self._parse_match_extras(raw, event_name, sport)

    def _parse_events(self, raw_events: list[dict], sport: str) -> list[tuple[str, Market | None, str | None]]:
        """(nombre del evento, mercado 1X2 o None si no es válido, href de su ficha
        o None) por cada partido bruto del listado."""
        events = []
        for event in raw_events:
            teams = event.get("teams", [])
            if len(teams) != 2:
                continue
            event_name = f"{teams[0].strip()} vs. {teams[1].strip()}"
            odds = [self._to_float(o) for o in event.get("odds", [])]
            market = None
            if len(odds) == 3 and all(o is not None for o in odds):
                outcomes = [
                    Outcome(name="1", bookmaker=self.name, odds=odds[0]),
                    Outcome(name="X", bookmaker=self.name, odds=odds[1]),
                    Outcome(name="2", bookmaker=self.name, odds=odds[2]),
                ]
                market = Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes)
            events.append((event_name, market, event.get("href")))
        return events

    def _parse_match_extras(self, raw: dict, event_name: str, sport: str) -> list[Market]:
        markets = []
        for key, (market_type, label_map) in _EXTRA_MARKETS.items():
            block = raw.get(key)
            market = self._parse_labelled_market(block, label_map, market_type, event_name, sport)
            if market is not None:
                markets.append(market)
        return markets

    def _parse_labelled_market(
        self, block: dict | None, label_map: dict[str, str], market_type: str, event_name: str, sport: str
    ) -> Market | None:
        if not block:
            return None
        odds = [self._to_float(o) for o in block.get("odds", [])]
        raw_labels = block.get("labels", [])
        if len(odds) != len(raw_labels) or len(raw_labels) != len(label_map) or any(o is None for o in odds):
            return None
        by_name: dict[str, float] = {}
        for raw_label, odd in zip(raw_labels, odds):
            name = label_map.get(raw_label.strip())
            if name is None or name in by_name:
                return None  # etiqueta desconocida o resultado repetido
            by_name[name] = odd
        if set(by_name) != set(label_map.values()):
            return None
        outcomes = [Outcome(name=name, bookmaker=self.name, odds=by_name[name]) for name in label_map.values()]
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        if not raw:
            return None
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError:
            return None
        return value if value > 1.0 else None
