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

Sin hora de inicio exacta en el listado (solo "Hoy"/"Mañana"/día de la semana +
hora, sin fecha completa), así que `Market.start_time` se deja `None`, igual
que en `providers/sportium.py`.

**Ampliado 2026-09-25**: la ficha de cada partido (misma app, sin API JSON
usable, ver arriba) organiza sus ~90 mercados en pestañas ("Goles", "Córneres
y tarjetas", "Mitad"...) navegables por fragmento de URL
(`<url-del-partido>/#goles`, sin necesidad de hacer click — un `page.goto`
directo a la URL con `#` ya carga esa pestaña). Cada mercado es un
`<details data-testid="sports-expandable-accordion">` con un `<summary>`
(nombre del mercado) y una `<table>` con cabeceras `<thead>` que YA dan los
nombres de resultado (equipos/"Empate" para 3 vías, "Más de"/"Menos de" o
"Sí"/"No" para 2 vías) y una fila por línea en `<tbody>` — **el contenido está
en el DOM aunque el `<details>` esté cerrado** (comprobado en vivo: un
mercado colapsado sigue teniendo sus filas), así que no hace falta clicar
cada mercado individualmente, solo cargar la pestaña. Implementados: 1X2 de
la 1ª parte ("Descanso"), Más/Menos de goles (partido y 1ª parte, todas las
líneas), Ambos equipos marcan (partido y 1ª parte, identificados por el texto
exacto de su fila dentro de la tabla "Mercados de Ambos equipos anotan", que
mezcla varios mercados distintos), y **córners/tarjetas** (total, por equipo,
y "equipo con más córners" 1X2) — el primer cruce de córners con una fuente
fuera de Altenar/Kambi/bwin/bet777. Se probó y descartó "Hándicap de
Córners": mismo patrón de hándicap de 3 vías con empate ya rechazado en
Zebet/Versus/888sport/William Hill (headers Local/Empate/Visitante en vez de
2 vías) — quinta vez que aparece esta forma en una casa distinta. Como cada
mercado nuevo exige cargar una página de Playwright por pestaña (no hay API
JSON, a diferencia de bet777/888sport/William Hill), la segunda pasada se
limita a `extra_markets_max_matches` partidos (25 por defecto, sin horizonte
porque el listado no da fecha exacta) leídos con concurrencia acotada sobre
el mismo navegador.

**Ampliado 2026-09-29 con Doble Oportunidad (DC)**: a diferencia de las 3 pestañas de
arriba, vive en una 4ª pestaña, "Todos los mercados" (`#todos-los-mercados`), cuyo
contenido SÍ necesita un clic - verificado en vivo, ver `EXTRA_TABS`/`_extract_double_chance`.
Ese clic tropezó con un banner de cookies OneTrust que solo aparecía con Playwright headless
real, no en el Browser pane (mismo patrón ya visto en este proyecto: el navegador interactivo
no basta como señal, aquí al revés - lo que SÍ funcionaba en el pane fallaba en headless
real por el banner, no por un bloqueo del sitio). El hándicap que también trae esa pestaña
es el mismo patrón de 3 vías con notación de marcador ya rechazado 6 veces en este repo
(ver `EXTRA_TABS`), así que no se implementa pese a estar disponible. Verificado en vivo
end-to-end con Playwright real (no solo el Browser pane): 4 de 5 partidos de prueba, valores
idénticos a los capturados a mano.
"""

import asyncio
import logging
import re
import time

from playwright.async_api import async_playwright

from engine.matching import peer_coverage
from engine.models import Market, Outcome
from providers.altenar import _fmt_line
from providers.base import OddsProvider
from providers.browser import block_heavy_resources
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

BOOKMAKER = "pokerstars"
DEFAULT_URL = "https://www.pokerstars.es/sports/futbol/1/matches/"
SITE_ORIGIN = "https://www.pokerstars.es"
DEFAULT_EXTRA_MARKETS_MAX_MATCHES = 25
# Cada hueco de concurrencia es una PESTAÑA de Chromium abierta a la vez (memoria real, no
# CPU). Bajado de 6 a 3 el 2026-09-28 (mismo motivo que providers/sportium.py:
# DEFAULT_EXTRA_MARKETS_CONCURRENCY, ver ese comentario) - aquí pesa más porque desde el mismo
# día esta fase puede arrancar YA (`refines`/`_refine` en engine/scan.py) mientras Sportium y
# otras fuentes con navegador todavía están leyendo, en vez de esperar a que todas terminen.
DEFAULT_EXTRA_MARKETS_CONCURRENCY = 3
# Tope de tiempo de TODA la lectura de fichas (ver `_fetch_extra_markets`), y lo mínimo que
# debe quedar para que merezca la pena empezar otra pestaña.
DEFAULT_EXTRA_MARKETS_BUDGET_SECONDS = 60.0
MIN_TAB_BUDGET_MS = 3000
# Fragmentos de URL de las pestañas de la ficha de partido que traen mercados
# nuevos; "Populares" (sin fragmento) ya se cubre con el 1X2 del listado.
#
# "todos-los-mercados" añadido 2026-09-29 (verificado en vivo con el Browser pane en 2
# partidos reales): a diferencia de las otras 3 pestañas, aquí el contenido NO está en el
# DOM hasta hacer clic (confirmado: el acordeón de "Doble oportunidad" pasa de
# `hasTable/rows vacío` a sus 3 cuotas reales solo tras clicar su <summary>) - por eso esta
# pestaña se trata aparte en `fetch_tab`/`_extract_double_chance`, en vez de con
# `_EXTRACT_ACCORDIONS_JS` como las demás. De sus ~58-100 mercados (verificados en vivo:
# "Marcador al descanso", "Goleadores", "Resultado correcto", combinadas...) solo Doble
# Oportunidad tiene pareja con la que cruzar en este repo; el "hándicap" que también trae
# esta pestaña ("Apuestas con hándicap"/"Hándicaps alternativos") es el mismo patrón de 3
# vías con notación de marcador ya rechazado 6 veces en otras casas (Zebet/Versus/888sport/
# William Hill/Sportium/PokerStars mismo, ver `_THREE_WAY_TITLES`), así que NO se implementa
# pese a estar disponible - confirmado en vivo, no una suposición.
EXTRA_TABS = ("goles", "corneres-y-tarjetas", "mitad", "todos-los-mercados")
DC_TAB = "todos-los-mercados"
DC_MARKET_TITLE = "Doble oportunidad"
# El clic de Doble Oportunidad reveló un banner de cookies OneTrust (confirmado en vivo con
# Playwright headless real el 2026-09-29, no visible en el Browser pane porque ya lo había
# aceptado antes sin querer) que intercepta el clic: "element intercepts pointer events".
# Las otras 3 pestañas nunca clican nada, por eso nunca lo tropezaron. Mismo patrón que
# `_COOKIE_ACCEPT_SELECTOR` de providers/zebet.py.
_COOKIE_ACCEPT_SELECTOR = "#onetrust-accept-btn-handler"
# En la VM (no en el sandbox de desarrollo, donde el primer clic bastó - mismo tipo de
# diferencia por red/IP ya visto con Sportium/William Hill en esta sesión) el primer clic a
# veces abre el panel detallado "Centro de preferencias de privacidad" en vez de cerrar el
# banner sin más: confirmado en producción por `onetrust-pc-dark-filter`/`onetrust-policy-text`
# interceptando el clic de Doble Oportunidad. Su propio botón de aceptar todo.
_COOKIE_CONFIRM_PREFERENCES_SELECTOR = "#accept-recommended-btn-handler"

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
            const link = participants.closest('a');
            const href = link ? link.getAttribute('href') : null;
            return { home, away, odds, href };
        }).filter(Boolean);
        return { heading, marketHeader, events };
    });
}"""

# Cada mercado de la ficha de partido es un <details> con un <summary> (su
# nombre) y una <table>: <thead> da los nombres de resultado (equipos/"Empate"
# para mercados a 3 vías, "Más de"/"Menos de" o "Sí"/"No" para 2 vías) y
# <tbody> una fila por línea. El contenido ya está en el DOM aunque el
# <details> esté cerrado (verificado en vivo), así que no hace falta clicar
# cada mercado, solo cargar la pestaña (ver EXTRA_TABS).
_EXTRACT_ACCORDIONS_JS = """() => {
    const accs = document.querySelectorAll('[data-testid="sports-expandable-accordion"]');
    const out = [];
    for (const acc of accs) {
        const summary = acc.querySelector('summary');
        const title = summary ? summary.textContent.trim() : null;
        const table = acc.querySelector('table');
        if (!table) continue;
        const headerCells = table.querySelectorAll('thead tr th, thead tr td');
        const headers = Array.from(headerCells).map(td => td.textContent.trim());
        const rows = Array.from(table.querySelectorAll('tbody tr')).map(
            tr => Array.from(tr.children).map(td => td.textContent.trim())
        );
        out.push({ title, headers, rows });
    }
    return out;
}"""


# Doble Oportunidad se renderiza como 3 botones `[data-testid="selection"]` (mismo
# componente que el 1X2 del listado), no como <table> - por eso necesita su propia
# extracción en vez de `_EXTRACT_ACCORDIONS_JS`. La etiqueta ("Moldavia y empate") y la
# cuota ("1,40") viven en el mismo nodo concatenadas sin separador; se clona la fila y se
# quita el botón para aislar la etiqueta, en vez de partir el texto por una expresión
# regular (más frágil: un nombre de equipo con coma o número lo rompería).
_EXTRACT_DC_JS = """() => {
    const accs = document.querySelectorAll('[data-testid="sports-expandable-accordion"]');
    const acc = Array.from(accs).find(a => a.querySelector('summary')?.textContent.trim() === '""" + DC_MARKET_TITLE + """');
    if (!acc) return null;
    return Array.from(acc.querySelectorAll('[data-testid="selection"]')).map(sel => {
        const row = sel.parentElement.parentElement;
        const clone = row.cloneNode(true);
        const btn = clone.querySelector('[data-testid="selection"]');
        if (btn) btn.remove();
        return { label: clone.textContent.trim(), odds: sel.textContent.trim() };
    });
}"""


def _parse_odds(raw: str) -> float | None:
    try:
        value = float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return None
    return value if value > 1.0 else None


# `<summary>` (nombre del mercado) -> plantilla de market_type, para las tablas
# de 2 vías (Más de/Menos de) con una fila por línea. Verificado en vivo el
# 2026-09-25 contra Italia-Bélgica (UEFA Nations League).
_OU_TABLE_FAMILIES = {
    "Más/menos de goles": "OU_{line}",
    "Primera mitad - Más/menos de goles": "OU_HT_{line}",
    "Total de córneres": "CORNERS_OU_{line}",
    "Total de córneres del equipo local": "CORNERS_OU_HOME_{line}",
    "Total de córneres del equipo visitante": "CORNERS_OU_AWAY_{line}",
    "Total de tarjetas": "CARDS_OU_{line}",
    "Total de tarjetas del equipo local en un partido": "CARDS_OU_HOME_{line}",
    "Total de tarjetas del equipo visitante en un partido": "CARDS_OU_AWAY_{line}",
}
# La tabla "Mercados de Ambos equipos anotan" mezcla varias filas (Ambos
# marcan, sin empate, 2+ goles cada uno...) bajo el mismo título: solo estas
# dos, por el texto EXACTO de su fila, son el BTTS simple que ya emiten el
# resto de fuentes.
_BTTS_ROWS = {
    "¿Ambos equipos anotan?": "BTTS",
    "Ambos Equipos Marcan en la 1ª Parte": "BTTS_HT",
}
# Tablas de 3 vías cuyas cabeceras SON los nombres de resultado (equipo local/
# "Empate"/equipo visitante), una única fila con las 3 cuotas.
_THREE_WAY_TITLES = {
    "Descanso": "1X2_HT",
    "Equipo con más corners totales": "CORNERS_1X2",
}
_LINE_RE = re.compile(r"(\d+,\d+)")


def _extract_line(text: str) -> str | None:
    """La línea siempre tiene coma decimal (las líneas de gol/córner/tarjeta
    son ",5" para evitar empates); la coma es obligatoria en la regex para no
    confundirla con un número suelto del propio texto ("Goles en la 1.a
    mitad - 2,5" tiene un "1" de "1.a" antes de la línea real)."""
    match = _LINE_RE.search(text)
    if not match:
        return None
    return _fmt_line(float(match.group(1).replace(",", ".")))


def _parse_ou_table(headers: list[str], rows: list[list[str]], template: str, event_name: str) -> list[Market]:
    if len(headers) < 3 or headers[1] not in ("Más de", "Sí") or headers[2] not in ("Menos de", "No"):
        return []
    side_names = ("Over", "Under") if headers[1] == "Más de" else ("Yes", "No")
    markets = []
    for row in rows:
        if len(row) < 3:
            continue
        line = _extract_line(row[0])
        first, second = _parse_odds(row[1]), _parse_odds(row[2])
        if line is None or first is None or second is None:
            continue
        markets.append(Market(
            event=event_name, sport="futbol", market_type=template.format(line=line),
            outcomes=[
                Outcome(name=side_names[0], bookmaker=BOOKMAKER, odds=first),
                Outcome(name=side_names[1], bookmaker=BOOKMAKER, odds=second),
            ],
        ))
    return markets


def _parse_btts_table(headers: list[str], rows: list[list[str]], event_name: str) -> list[Market]:
    if len(headers) < 3 or headers[1] != "Sí" or headers[2] != "No":
        return []
    markets = []
    for row in rows:
        if len(row) < 3:
            continue
        market_type = _BTTS_ROWS.get(row[0].strip())
        yes, no = _parse_odds(row[1]), _parse_odds(row[2])
        if market_type is None or yes is None or no is None:
            continue
        markets.append(Market(
            event=event_name, sport="futbol", market_type=market_type,
            outcomes=[Outcome(name="Yes", bookmaker=BOOKMAKER, odds=yes), Outcome(name="No", bookmaker=BOOKMAKER, odds=no)],
        ))
    return markets


def _parse_three_way_table(
    headers: list[str], rows: list[list[str]], market_type: str, home_name: str, away_name: str, event_name: str
) -> list[Market]:
    """Tabla cuyas cabeceras son los nombres de resultado en sí (p.ej.
    "Italia"/"Empate"/"Bélgica"): se descarta si no encajan exactamente los
    3 esperados, en vez de asumir un orden fijo por columna - mismo criterio
    de "fallo seguro" que el resto de proveedores de este repo."""
    if len(headers) != 3:
        return []
    label_by_index: dict[int, str] = {}
    for index, header in enumerate(headers):
        header = header.strip()
        if header == home_name:
            label_by_index[index] = "1"
        elif header == away_name:
            label_by_index[index] = "2"
        elif header == "Empate":
            label_by_index[index] = "X"
    if set(label_by_index.values()) != {"1", "X", "2"}:
        return []
    markets = []
    for row in rows:
        if len(row) != 3:
            continue
        pairs = []
        for index, cell in enumerate(row):
            odds = _parse_odds(cell)
            if odds is None:
                pairs = None
                break
            pairs.append((label_by_index[index], odds))
        if not pairs:
            continue
        markets.append(Market(
            event=event_name, sport="futbol", market_type=market_type,
            outcomes=[Outcome(name=label, bookmaker=BOOKMAKER, odds=odds) for label, odds in pairs],
        ))
    return markets


def _parse_double_chance(rows: list[dict] | None, home_name: str, away_name: str) -> Market | None:
    """3 filas de `_EXTRACT_DC_JS` ({label, odds}) -> DC (1X/X2/12). El resultado se
    identifica por qué nombres de equipo aparecen en la etiqueta ("Moldavia y empate" ->
    local+empate -> 1X), no por su posición: verificado en vivo en 2 partidos que el orden
    es siempre local+empate/visitante+empate/local+visitante, pero derivarlo del texto es
    el mismo criterio de fallo seguro que el resto de este proveedor (ver
    `_parse_three_way_table`) - una etiqueta inesperada descarta el mercado entero en vez
    de adivinar."""
    if not rows or len(rows) != 3:
        return None
    outcomes = []
    for row in rows:
        label, odds = row.get("label") or "", _parse_odds(row.get("odds") or "")
        has_home, has_away = home_name in label, away_name in label
        if odds is None or not (has_home or has_away):
            return None  # ni local ni visitante en la etiqueta: formato inesperado
        name = "12" if has_home and has_away else "1X" if has_home else "X2"
        outcomes.append(Outcome(name=name, bookmaker=BOOKMAKER, odds=odds))
    if {o.name for o in outcomes} != {"1X", "X2", "12"}:
        return None  # dos filas con el mismo resultado: algo fue mal, no se adivina
    return Market(event=f"{home_name} vs. {away_name}", sport="futbol", market_type="DC", outcomes=outcomes)


def parse_extra_markets(raw_accordions: list[dict], home_name: str, away_name: str) -> list[Market]:
    """Convierte los `<details>` de una pestaña (`_EXTRACT_ACCORDIONS_JS`) en
    los mercados nuevos: DC y hándicap de gol a partido completo NO están en
    ninguna de las 3 pestañas leídas (`EXTRA_TABS`) — viven detrás de la
    búsqueda "Todos los mercados", que exige un clic por mercado, más caro y
    dejado para una futura sesión, mismo criterio incremental que el resto de
    fuentes de este repo (ver docstring del módulo)."""
    event_name = f"{home_name} vs. {away_name}"
    found: dict[str, Market] = {}
    for acc in raw_accordions:
        title = (acc.get("title") or "").strip()
        headers = acc.get("headers") or []
        rows = acc.get("rows") or []
        parsed: list[Market] = []
        if title in _OU_TABLE_FAMILIES:
            parsed = _parse_ou_table(headers, rows, _OU_TABLE_FAMILIES[title], event_name)
        elif title == "Mercados de Ambos equipos anotan":
            parsed = _parse_btts_table(headers, rows, event_name)
        elif title in _THREE_WAY_TITLES:
            parsed = _parse_three_way_table(headers, rows, _THREE_WAY_TITLES[title], home_name, away_name, event_name)
        for market in parsed:
            found.setdefault(market.market_type, market)
    return list(found.values())


def select_crossed_matches(
    listing: list[tuple[str, str, str]], peer_markets: list[Market], limit: int
) -> list[tuple[str, str, str]]:
    """De los partidos del listado (local, visitante, enlace), los que otra casa también
    lista (misma regla de cruce que el motor, `engine.matching.peer_coverage`), primero los
    que cubren más casas distintas, hasta `limit`. Empate: se conserva el orden del listado."""
    coverage = peer_coverage([f"{home} vs. {away}" for home, away, _ in listing], peer_markets, "futbol", BOOKMAKER)
    crossed = [item for item in listing if f"{item[0]} vs. {item[1]}" in coverage]
    crossed.sort(key=lambda item: -coverage[f"{item[0]} vs. {item[1]}"])  # sort estable
    return crossed[:limit]


class PokerStarsProvider(OddsProvider):
    """PokerStars Sports por DOM (ver docstring del módulo). 1X2 de fútbol
    dentro del horizonte que la propia web decide mostrar en `/matches/` (una
    sola página, barato) más OU/BTTS/1X2_HT/CORNERS/CARDS/DC leyendo 4 pestañas de
    la ficha de cada partido (ver `EXTRA_TABS`), limitado a
    `extra_markets_max_matches` porque cada pestaña es una página de Playwright
    aparte (sin API JSON, a diferencia de bet777/888sport/William Hill).

    `fetch_dc`: la pestaña de Doble Oportunidad necesita un clic (ver
    `_extract_double_chance`) que el panel de cookies OneTrust bloquea de forma
    consistente en la VM de producción pese a 2 intentos de arreglo (2026-09-29:
    banner simple + panel detallado "Centro de preferencias") - confirmado en
    vivo: 0 mercados DC de pokerstars en la base de datos en ~19h de ciclos tras
    el 2º arreglo, siempre el mismo timeout con "onetrust-pc-dark-filter...
    intercepts pointer events". Se desactiva en producción (ver
    `scripts/scan_once_action.py`) para no gastar tiempo de ciclo en un intento
    que nunca produce mercados, igual que `SportiumProvider.fetch_extra_markets`."""

    name = BOOKMAKER
    uses_browser = True  # lanza Chromium: el escaneo limita cuantos a la vez (MAX_CONCURRENT_FETCHES)
    refines = True

    def __init__(
        self,
        url: str = DEFAULT_URL,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
        extra_markets_max_matches: int = DEFAULT_EXTRA_MARKETS_MAX_MATCHES,
        extra_markets_concurrency: int = DEFAULT_EXTRA_MARKETS_CONCURRENCY,
        extra_markets_budget_seconds: float = DEFAULT_EXTRA_MARKETS_BUDGET_SECONDS,
        fetch_dc: bool = True,
    ):
        self.url = url
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women
        self.extra_markets_max_matches = extra_markets_max_matches
        self.extra_markets_concurrency = extra_markets_concurrency
        self.extra_markets_budget_seconds = extra_markets_budget_seconds
        # Ver `fetch_dc` en el docstring de la clase: en producción (VM) el panel de
        # cookies OneTrust bloquea el clic de esta pestaña de forma consistente pese a
        # 2 intentos de arreglo (2026-09-29), así que se desactiva ahí manteniendo el
        # código/tests intactos por si se retoma (mismo patrón que
        # `SportiumProvider.fetch_extra_markets`).
        self.fetch_dc = fetch_dc
        # Partidos del listado (local, visitante, enlace a su ficha) para la 2ª pasada.
        self._listing: list[tuple[str, str, str]] = []

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        """Primera pasada: SOLO el 1X2 del listado (una página, unos segundos). Los mercados
        de cada ficha se leen en `refine`, cuando ya se sabe qué partidos lista otra casa."""
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        return asyncio.run(self._fetch_markets_async())

    async def _fetch_markets_async(self) -> list[Market]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await block_heavy_resources(await browser.new_page())
            try:
                await page.goto(self.url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_selector('[data-testid="event-list"]', timeout=20000)
                await page.wait_for_selector('[data-testid="selection"]', timeout=20000)
                raw_groups = await page.evaluate(_EXTRACT_JS)
            finally:
                await page.close()
                await browser.close()

        markets = self._parse_groups(raw_groups)
        href_by_names = self._href_by_names(raw_groups)
        self._listing = [
            (home, away, href_by_names[(home, away)])
            for home, away in (market.event.split(" vs. ", 1) for market in markets)
            if (home, away) in href_by_names
        ]
        return markets

    def refine(self, sports: list[str], peer_markets: list[Market]) -> list[Market]:
        """Segunda pasada: OU/BTTS/1X2_HT/CORNERS/CARDS/DC de las fichas, solo de los partidos
        que alguna OTRA casa también lista (los únicos que pueden cruzarse), los más
        cubiertos primero y con un tope de tiempo. En la VM (2 vCPU) leer las fichas de los
        25 primeros partidos del listado, sin mirar si alguien más los lista, era el 90 % de
        un ciclo entero: medido el 2026-09-28, ~3 min 40 s de 3 min 55 s."""
        matches = select_crossed_matches(self._listing, peer_markets, self.extra_markets_max_matches)
        logger.info(
            "PokerStars: %d de %d partidos del listado los lista otra casa%s",
            len(matches), len(self._listing), "" if matches else " (no se lee ninguna ficha)",
        )
        if not matches:
            return []
        return asyncio.run(self._refine_async(matches))

    async def _refine_async(self, matches: list[tuple[str, str, str]]) -> list[Market]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await self._fetch_extra_markets(browser, matches)
            finally:
                await browser.close()

    @staticmethod
    def _href_by_names(raw_groups: list[dict]) -> dict[tuple[str, str], str]:
        hrefs: dict[tuple[str, str], str] = {}
        for group in raw_groups:
            for event in group.get("events", []):
                home, away, href = event.get("home"), event.get("away"), event.get("href")
                if home and away and href:
                    hrefs.setdefault((home, away), href)
        return hrefs

    async def _fetch_extra_markets(self, browser, matches: list[tuple[str, str, str]]) -> list[Market]:
        """OU/BTTS/1X2_HT/CORNERS/CARDS/DC de `matches` (ver `parse_extra_markets` y
        `_parse_double_chance`), cargando las 4 pestañas de `EXTRA_TABS` de cada ficha en
        paralelo con concurrencia acotada. Un fallo en una pestaña suelta no descarta el
        resto del partido, igual que el resto de proveedores concurrentes de
        este repo (Altenar, bwin, William Hill)."""
        if not matches:
            return []
        semaphore = asyncio.Semaphore(self.extra_markets_concurrency)
        # Tope de tiempo de toda la fase: las pestañas que no hayan empezado al agotarse se
        # saltan (el semáforo es FIFO, así que se pierden las de los partidos menos
        # cubiertos, que van al final) y las que sí han empezado no esperan más que lo que
        # queda. Sin tope, un puñado de pestañas que agotan su espera alargaba el ciclo.
        deadline = time.monotonic() + self.extra_markets_budget_seconds
        skipped = 0
        tabs = EXTRA_TABS if self.fetch_dc else tuple(t for t in EXTRA_TABS if t != DC_TAB)

        async def fetch_tab(href: str, tab: str) -> list[dict]:
            nonlocal skipped
            async with semaphore:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms < MIN_TAB_BUDGET_MS:
                    skipped += 1
                    return []
                page = await block_heavy_resources(await browser.new_page())
                try:
                    await page.goto(
                        f"{SITE_ORIGIN}{href}#{tab}", timeout=min(20000, remaining_ms), wait_until="domcontentloaded"
                    )
                    remaining_ms = max(int((deadline - time.monotonic()) * 1000), MIN_TAB_BUDGET_MS)
                    await page.wait_for_selector(
                        '[data-testid="sports-expandable-accordion"]', timeout=min(15000, remaining_ms)
                    )
                    if tab == DC_TAB:
                        return await self._extract_double_chance(page, remaining_ms)
                    return await page.evaluate(_EXTRACT_ACCORDIONS_JS)
                except Exception:
                    logger.warning("PokerStars: fallo leyendo %s#%s", href, tab, exc_info=True)
                    return []
                finally:
                    await page.close()

        async def fetch_match(home: str, away: str, href: str) -> list[Market]:
            tab_results = await asyncio.gather(*[fetch_tab(href, tab) for tab in tabs])
            # DC va aparte: su resultado no es un acordeón de tabla (`{title, headers, rows}`
            # como `_EXTRACT_ACCORDIONS_JS`) sino filas de botones (`_EXTRACT_DC_JS`), así
            # que `parse_extra_markets` no sabría clasificarlo.
            accordions, dc_rows = [], None
            for tab, result in zip(tabs, tab_results):
                if tab == DC_TAB:
                    dc_rows = result or None
                else:
                    accordions.extend(result)
            markets = parse_extra_markets(accordions, home, away)
            dc_market = _parse_double_chance(dc_rows, home, away)
            if dc_market is not None:
                markets.append(dc_market)
            return markets

        results = await asyncio.gather(*[fetch_match(home, away, href) for home, away, href in matches])
        markets = [market for sub in results for market in sub]
        logger.info(
            "PokerStars: %d mercados nuevos (OU/BTTS/1X2_HT/CORNERS/CARDS%s) en %d partidos%s",
            len(markets), "/DC" if self.fetch_dc else "", len(matches),
            f" ({skipped} pestañas saltadas por el tope de {self.extra_markets_budget_seconds:.0f}s)" if skipped else "",
        )
        return markets

    @staticmethod
    async def _extract_double_chance(page, remaining_ms: int) -> list[dict]:
        """Doble Oportunidad, dentro de la pestaña `DC_TAB` ya cargada (ver `fetch_tab`):
        a diferencia de las otras 3 pestañas, aquí SÍ hace falta un clic (verificado en
        vivo, ver el comentario de `EXTRA_TABS`) antes de que sus cuotas aparezcan en el
        DOM. `.filter(has=...)` localiza el acordeón por el texto EXACTO de su `<summary>`
        para no confundirlo con "Doble oportunidad y más/menos de X,5 goles" (mismo
        prefijo, MISMO texto si no fuera por `exact=True`)."""
        try:
            await page.click(_COOKIE_ACCEPT_SELECTOR, timeout=2000)
        except Exception:
            pass  # ya aceptado en una página previa de esta misma sesión, o no apareció
        try:
            await page.wait_for_selector("#onetrust-consent-sdk", state="hidden", timeout=3000)
        except Exception:
            # El banner sigue encima: en la VM a veces el primer clic abre el panel
            # detallado en vez de cerrar directamente (ver el comentario de
            # `_COOKIE_CONFIRM_PREFERENCES_SELECTOR`). Se intenta su propio botón antes de
            # seguir; si tampoco funciona, el clic de Doble Oportunidad de más abajo
            # fallará igual que cualquier otra pestaña y quedará registrado como tal.
            try:
                await page.click(_COOKIE_CONFIRM_PREFERENCES_SELECTOR, timeout=2000)
                await page.wait_for_selector("#onetrust-consent-sdk", state="hidden", timeout=3000)
            except Exception:
                pass
        locator = page.locator('[data-testid="sports-expandable-accordion"]').filter(
            has=page.get_by_text(DC_MARKET_TITLE, exact=True)
        )
        if await locator.count() == 0:
            return []
        summary = locator.first.locator("summary")
        await summary.click(timeout=min(5000, remaining_ms))
        try:
            await locator.first.locator('[data-testid="selection"]').first.wait_for(timeout=min(5000, remaining_ms))
        except Exception:
            return []  # el clic no abrió el mercado (cambio de sitio, mercado suspendido...)
        return await page.evaluate(_EXTRACT_DC_JS) or []

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
