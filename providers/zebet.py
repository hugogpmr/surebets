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

**Doble oportunidad, Ambos marcan, Par/Impar, Más/Menos y Hándicap (añadido
2026-09-24)**: a diferencia del 1X2 (que sale entero en el listado de
competición), estos mercados solo están en la **ficha de cada partido**
(`/es/event/<slug>`, enlazada desde `.bet-activebets a` de cada bloque del
listado) - así que amplían el coste de un ciclo: una navegación de página por
partido además de la del listado (~20 páginas para LaLiga completa), no una sola
petición JSON como en otras casas de este repo.

Cada uno de los ~47 grupos de la ficha es un bloque `.bet-question[data-t="..."]`
seguido, dentro del mismo `.item-content`, por sus `.pmq-cote`/`.pmq-cote-acteur`
(uno o varios pares, según el mercado). El texto de la pregunta (no la etiqueta
de cada resultado, que a veces no lleva la línea) es la clave para saber qué
mercado es y, en hándicap/más-menos, la línea:

- `data-t="Doble oportunidad"` - único en la página, resultados "1X"/"12"/"X2" ->
  `DC`.
- `data-t="¿Ambos equipos marcarán al menos un gol?"` - único, "Si"/"No" -> `BTTS`.
- `data-t="Par - Impar"` - **el mismo código se reutiliza para el partido completo,
  cada equipo por separado y cada mitad** (verificado en vivo en 2 partidos
  distintos): el bloque del partido completo se identifica por el texto exacto y
  estable "¿El número de goles marcados será par o impar?" (sin nombre de equipo
  interpolado, a diferencia de los otros); "Par"/"Impar" -> `OE`.
- **Más/Menos de goles** (`data-t="Más de / Menos de"` para partido completo Y 1ª
  mitad juntos - se distinguen por el texto exacto de la pregunta -, y
  `data-t="Más de / Menos de (2a mitad)"` aparte para la 2ª): todas las líneas
  disponibles (0.5, 1.5, 2.5...) van como resultados "Más de <línea>"/"Menos de
  <línea>" bajo la MISMA pregunta, a diferencia del 1X2 - se emparejan por línea
  como en `providers/bet777.py`. -> `OU`/`OU_HT`/`OU_2H`.
- **Hándicap de goles**: esta casa tiene DOS formatos distintos para lo mismo, y
  solo uno de los dos cruza con el resto de casas de este repo. El que SÍ se
  implementa es el de línea decimal con signo ("Hándicap (+0.5)"/"Hándicap
  (-1.5)"), 2 resultados (solo local/visitante, sin empate) - el mismo hándicap
  asiático que ya usan Altenar/Kambi/Winamax/bet777/CuotasAhora -> `AH`/`AH_HT`/
  `AH_2H`. El otro formato, con notación de marcador ("Hándicap (2:0)", 3
  resultados incluido empate), se descarta a propósito: ninguna otra fuente de
  este repo lo emite, así que nunca podría cruzar. Ambos formatos comparten
  `data-t` en las variantes por mitad (`"Hándicap del periodo"`/`"Margen al
  descanso"`), así que la línea y el número de resultados se leen del texto de la
  pregunta, no del `data-t`, para no confundirlos.
- El resto de los grupos de la ficha (combinadas, marcador exacto, margen de
  victoria, más/menos por equipo, apuestas de jugador...) quedan fuera: no son de
  dos/tres resultados exhaustivos y limpios, o no tienen pareja en otra fuente.
"""

import asyncio
import re

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

# Cada mercado de la ficha es un `.bet-question[data-t]` seguido, dentro del mismo
# `.item-content`, de sus resultados: se vuelcan TODOS los bloques de la página en
# una sola pasada (la clasificación por data-t/texto de pregunta se hace en Python,
# ver docstring del módulo) en vez de seleccionar cada mercado por separado, porque
# el mismo data-t se reutiliza para variantes distintas (Par-Impar, Hándicap...).
_EXTRACT_MATCH_EXTRAS_JS = """() => {
    return Array.from(document.querySelectorAll('.bet-question')).map(q => {
        const wrapper = q.closest('.item-content');
        if (!wrapper) return null;
        return {
            dataT: q.getAttribute('data-t'),
            question: q.textContent.replace(/\\s+/g, ' ').trim(),
            odds: Array.from(wrapper.querySelectorAll('.pmq-cote')).map(e => e.textContent.trim()),
            labels: Array.from(wrapper.querySelectorAll('.pmq-cote-acteur')).map(e => e.textContent.trim()),
        };
    }).filter(Boolean);
}"""

# (market_type, {etiqueta de la web -> nombre de resultado}) por cada mercado de
# resultado fijo identificado por su data-t. Mismos prefijos y nombres de
# resultado que Altenar/Kambi/Winamax/CuotasAhora, para que crucen.
_DC_LABELS = {"1X": "1X", "12": "12", "X2": "X2"}
_BTTS_LABELS = {"Si": "Yes", "No": "No"}
_OE_LABELS = {"Impar": "Odd", "Par": "Even"}
# Par-Impar reutiliza el mismo data-t para el partido completo, cada equipo y cada
# mitad (verificado en vivo en 2 partidos distintos): el del partido completo se
# distingue por su texto exacto y estable, sin nombre de equipo interpolado.
_OE_FULL_MATCH_QUESTION = "¿El número de goles marcados será par o impar?"

# Más/menos de goles: mismo data-t para partido completo y 1ª mitad, distinguidos
# por el texto exacto de la pregunta; 2ª mitad tiene su propio data-t pero se
# identifica igual, por consistencia con las otras dos.
_OU_QUESTION_SUFFIX = {
    "¿Más o menos de goles?": "",
    "¿Más o menos de goles en el 1o tiempo?": "_HT",
    "¿Más o menos de goles en la 2ª mitad?": "_2H",
}
_OU_LABEL_RE = re.compile(r"^(Más|Menos) de (\d+(?:\.\d+)?)$")

# Hándicap de línea decimal con signo (el que cruza, ver docstring): el signo/línea
# se lee de la PREGUNTA, no de la etiqueta de cada resultado (la variante de 2ª
# mitad no repite la línea en la etiqueta, solo en la pregunta). El formato de
# marcador ("Hándicap (2:0)") no coincide con este patrón (los dos puntos no son
# un signo ni un decimal) y así queda excluido sin necesidad de mirar el data-t.
_AH_QUESTION_RE = re.compile(r"^Hándicap \(([+-]?\d+(?:\.\d+)?)\) - ¿Quién ganará (el partido|la 1ª mitad|la 2ª mitad)\?$")
_AH_PERIOD_SUFFIX = {"el partido": "", "la 1ª mitad": "_HT", "la 2ª mitad": "_2H"}


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
        """Doble oportunidad/Ambos marcan/Par-Impar/Más-Menos/Hándicap viven solo
        en la ficha del partido (ver docstring del módulo): una navegación de
        página más por partido. Un partido con la ficha rota no debe tumbar a los
        demás."""
        try:
            await page.goto("https://www.zebet.es" + href, timeout=20000, wait_until="load")
            await page.wait_for_selector('[data-t="Doble oportunidad"]', timeout=8000)
            raw_blocks = await page.evaluate(_EXTRACT_MATCH_EXTRAS_JS)
        except Exception:
            return []
        return self._parse_match_extras(raw_blocks, event_name, sport)

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

    def _parse_match_extras(self, raw_blocks: list[dict], event_name: str, sport: str) -> list[Market]:
        markets: list[Market] = []
        seen_types: set[str] = set()

        def emit(market: Market | None) -> None:
            if market is not None and market.market_type not in seen_types:
                seen_types.add(market.market_type)
                markets.append(market)

        for block in raw_blocks:
            data_t = block.get("dataT")
            question = (block.get("question") or "").strip()
            odds, labels = block.get("odds", []), block.get("labels", [])

            if data_t == "Doble oportunidad":
                emit(self._parse_labelled_market(odds, labels, _DC_LABELS, "DC", event_name, sport))
            elif data_t == "¿Ambos equipos marcarán al menos un gol?":
                emit(self._parse_labelled_market(odds, labels, _BTTS_LABELS, "BTTS", event_name, sport))
            elif data_t == "Par - Impar" and question == _OE_FULL_MATCH_QUESTION:
                emit(self._parse_labelled_market(odds, labels, _OE_LABELS, "OE", event_name, sport))
            elif question in _OU_QUESTION_SUFFIX:
                for market in self._parse_ou_lines(odds, labels, _OU_QUESTION_SUFFIX[question], event_name, sport):
                    emit(market)
            else:
                emit(self._parse_ah_block(question, odds, labels, event_name, sport))
        return markets

    def _parse_labelled_market(
        self, odds: list, labels: list, label_map: dict[str, str], market_type: str, event_name: str, sport: str
    ) -> Market | None:
        odds = [self._to_float(o) for o in odds]
        if len(odds) != len(labels) or len(labels) != len(label_map) or any(o is None for o in odds):
            return None
        by_name: dict[str, float] = {}
        for raw_label, odd in zip(labels, odds):
            name = label_map.get(raw_label.strip())
            if name is None or name in by_name:
                return None  # etiqueta desconocida o resultado repetido
            by_name[name] = odd
        if set(by_name) != set(label_map.values()):
            return None
        outcomes = [Outcome(name=name, bookmaker=self.name, odds=by_name[name]) for name in label_map.values()]
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    def _parse_ou_lines(self, odds: list, labels: list, suffix: str, event_name: str, sport: str) -> list[Market]:
        """Todas las líneas de "Más de / Menos de" vienen bajo la misma pregunta:
        se emparejan por línea, igual que providers/bet777.py."""
        by_line: dict[float, dict[str, float]] = {}
        for raw_label, raw_odd in zip(labels, odds):
            match = _OU_LABEL_RE.match(raw_label.strip())
            odd = self._to_float(raw_odd)
            if not match or odd is None:
                continue
            side = "Over" if match.group(1) == "Más" else "Under"
            by_line.setdefault(float(match.group(2)), {})[side] = odd
        markets = []
        for line, sides in sorted(by_line.items()):
            if set(sides) != {"Over", "Under"}:
                continue
            outcomes = [
                Outcome(name="Over", bookmaker=self.name, odds=sides["Over"]),
                Outcome(name="Under", bookmaker=self.name, odds=sides["Under"]),
            ]
            market_type = f"OU{suffix}_{self._fmt_line(line)}"
            markets.append(Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes))
        return markets

    def _parse_ah_block(self, question: str, odds: list, labels: list, event_name: str, sport: str) -> Market | None:
        """Solo el hándicap de línea decimal con signo (2 resultados) coincide con
        este patrón - ver docstring del módulo para por qué se descarta el de
        notación de marcador (3 resultados, sin pareja en otra fuente)."""
        match = _AH_QUESTION_RE.match(question)
        if not match:
            return None
        odds = [self._to_float(o) for o in odds]
        if len(odds) != 2 or any(o is None for o in odds):
            return None
        line = float(match.group(1))
        suffix = _AH_PERIOD_SUFFIX[match.group(2)]
        outcomes = [
            Outcome(name="1", bookmaker=self.name, odds=odds[0]),
            Outcome(name="2", bookmaker=self.name, odds=odds[1]),
        ]
        market_type = f"AH{suffix}_{self._fmt_line(line, signed=True)}"
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    @staticmethod
    def _fmt_line(value: float, signed: bool = False) -> str:
        text = str(int(value)) if value == int(value) else f"{value:g}"
        return "+" + text if signed and value > 0 else text

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        if not raw:
            return None
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError:
            return None
        return value if value > 1.0 else None
