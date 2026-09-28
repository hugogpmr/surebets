"""casasdeapuestas.com por HTML plano (httpx + BeautifulSoup, sin navegador): comparador
que agrega hasta ~25 casas en la página de cada evento, entre ellas varias que este
proyecto no tiene como fuente directa (bet365, Codere, William Hill, Retabet, Kirolbet,
Marca Apuestas, Casino Barcelona) - ver la investigación en vivo del 2026-09-27 (sesión
con el usuario, no queda escrita en ningún estudio .md todavía). A diferencia de
CuotasAhora/BetExplorer no hace falta Playwright: la página de cada partido
(`/cuotas/evento/<slug>/`) ya trae toda la cuota-por-casa-por-mercado en el HTML servido
por el servidor - confirmado con un `curl` normal sin cookies desde dos redes distintas,
HTTP 200, sin reto de Cloudflare. Solo se vio UN bloqueo puntual del WAF al pedir
`/robots.txt` (no reproducible al reintentar) - por eso ese fichero no se pide nunca aquí.

Descubrimiento de partidos en dos pasos, sin lista de ligas escrita a mano (a propósito:
el usuario pidió cobertura de "casi todos los países", y mantener esa lista a mano no
escala):

1. La página raíz de cada deporte (`/cuotas/<seccion>/`) trae un filtro de país que solo
   se activa por JavaScript en un navegador real: cada botón lleva la URL de su
   competición codificada en base64 en el atributo `data-league-id`. Es la ÚNICA forma de
   ver el catálogo completo - confirmado en vivo que el menú visible (`<a href>`) por sí
   solo se deja fuera competiciones reales (Serie B italiana, Ligue 2 francesa, WNBA,
   LNBP mexicana...). Se combinan ambas fuentes (enlaces visibles + `data-league-id`),
   deduplicadas.
2. La página de cada competición (`/cuotas/<seccion>/<pais>/<liga>/`) lista sus partidos
   próximos como `<div class="event" data-id="...">`, con el enlace al partido codificado
   igual en `data-lnk` dentro de `.event-teams`.

La página de cada partido (`/cuotas/evento/<slug>/`) es una lista PLANA de `<div
class="odd">`, uno por cada tupla (mercado, resultado, casa): `data-mercado` (nombre del
mercado en español), `data-nombre` (equipo/resultado tal cual lo llama el sitio) y
`data-bookie` (casa, en un `<div class="bookie">` anidado), más el texto de la cuota. No
hay bloques que recorrer: basta con leer todos los `.odd` de la página y agruparlos en
Python por `data-mercado` (ver `_extract_odds`/`parse_event_markets`).

Vocabulario de mercados verificado en vivo el 2026-09-27 contra fútbol (LaLiga),
baloncesto (NBA), tenis (ATP Tokio), hockey hielo (NHL), fútbol americano (NFL) y
balonmano (Bundesliga alemana): el mismo concepto cambia de nombre entre deportes
("Total de goles" en fútbol, "Total de puntos" en baloncesto/NFL, "Total de juegos" en
tenis, "Más/Menos Total Goles" en balonmano; el sufijo de mitad también difiere:
" - Primera mitad"/" - Segunda mitad" en fútbol vs " - 1º Mitad"/" - 2º Mitad" en NFL) -
se listan las variantes vistas en vez de asumir un patrón único que no existe.
"Ganador"/"Final del partido (1X2)"/"Ganador 1X2" se tratan como el mismo tipo de mercado
("¿quién gana?"): el nº de resultados que trae DE VERDAD decide si se emite como `ML`
(sin empate: 2 resultados) o `1X2` (con empate: 3 resultados), en vez de asumirlo por
deporte - fútbol americano y balonmano SÍ incluyen "Empate" en su "Ganador" (raro pero
real en esos reglamentos), baloncesto y tenis no.

Se dejan fuera a propósito (mismo criterio que el resto del proyecto: no exhaustivos, de
3 vías con notación de marcador, o sin ningún proveedor de aquí con el que cruzar):
"Marcador correcto", "Descanso/Final", "Hándicap Europeo" (3 vías con notación tipo
"2 -3", el mismo patrón ya rechazado 6 veces en Zebet/Versus/888sport/WilliamHill/
PokerStars/Sportium), "Gana a 0", "¿Primer equipo en marcar?", "Gana ambas mitades",
"Ambos equipos marcan en ambas mitades", "Gol en ambas mitades", "Último equipo en
marcar", "Apuestas de set (marcador exacto)".

Deportes: fútbol, baloncesto, tenis, balonmano y fútbol americano ya existían en el
proyecto (mismo valor de `sport` que el resto de proveedores para poder cruzar) - más
HOCKEY HIELO y TENIS DE MESA, que ningún otro proveedor de aquí cubre todavía (claves
nuevas `hockey`/`tenismesa`, sin guion bajo a propósito para no romper el truco
`key.split("_", 1)[0]` que ya usan Bet777/Sport888/etc. para leer `SPORTS` ignorando
sufijos de competición). Tenis de mesa no tenía ningún partido listado el 2026-09-27 (ni
en el menú visible ni en el filtro oculto) - puede ser temporada baja o que esa sección
del sitio simplemente no esté poblada; se deja conectado igualmente (si sigue vacío en
producción, no es un fallo del provider, hay que revisarlo más adelante).

`fast_recheck = True`: aunque es un comparador multi-casa (como CuotasAhora/BetExplorer),
su coste por partido es el de una API httpx normal (sin navegador), igual que
Bet777/WilliamHill/Sport888 - por escala (cientos de competiciones/partidos) sigue yendo
en `comparator_providers()`/el ciclo lento con caché, no en `direct_providers()`.
"""

import base64
import logging
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

BASE = "https://www.casasdeapuestas.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
}
DEFAULT_HORIZON_HOURS = 48

# Segmento de sección del sitio por cada deporte interno nuestro (ver docstring del
# módulo). "hockey" y "tenismesa" son claves nuevas de este proyecto, sin fuente directa
# hasta ahora.
SPORT_SECTIONS: dict[str, str] = {
    "futbol": "futbol",
    "baloncesto": "baloncesto",
    "tenis": "tenis",
    "balonmano": "balonmano",
    "americano": "futbol-americano",
    "hockey": "hockey-hielo",
    "tenismesa": "tenis-de-mesa",
}

# "¿Quién gana?" (2 o 3 resultados según traiga o no "Empate", ver `_winner_market`).
_WINNER_MARKETS = {"Final del partido (1X2)", "Ganador 1X2", "Ganador"}
# Resto de mercados fijos (sin línea), por nombre EXACTO de `data-mercado` (ya sin sufijo
# de mitad, ver `_split_period`) -> prefijo de `market_type`.
_TWO_WAY_MARKETS = {"Empate, apuesta no válida": "DNB"}
_SET_WINNER_MARKETS = {"Ganador del primer set": "ML_SET1", "Ganador del segundo set": "ML_SET2"}
_YES_NO_MARKETS = {"Ambos equipos marcan": "BTTS"}
_ODD_EVEN_MARKETS = {"Par/Impar": "OE"}
_DC_MARKETS = {"Doble oportunidad": "DC"}
# Mercados con línea: cada `data-mercado` de aquí agrupa varias líneas juntas
# ("Más de 0.5"/"Menos de 0.5", "Más de 0.75"/"Menos de 0.75"...) - ver `_ou_markets`.
_OU_MARKETS = {
    "Total de goles": "OU",
    "Total de puntos": "OU",
    "Total de juegos": "OU",
    "Más/Menos Total Goles": "OU",
    "Córners Totales": "CORNERS_OU",
}
# Hándicap asiático de 2 vías (nombre de equipo + línea firmada) - ver `_ah_markets`.
# "Hándicap Europeo" NO está aquí a propósito (ver docstring del módulo).
_AH_MARKETS = {
    "Hándicap Asiático": "AH",
    "Hándicap": "AH",
    "Hándicap de juegos": "AH",
}

_PERIOD_RE = re.compile(r"^(.+?) - (Primera mitad|Segunda mitad|1º Mitad|2º Mitad)$")
_PERIOD_SUFFIX = {"Primera mitad": "HT", "1º Mitad": "HT", "Segunda mitad": "2H", "2º Mitad": "2H"}

_OVER_RE = re.compile(r"^Más de (-?\d+(?:\.\d+)?)$")
_UNDER_RE = re.compile(r"^Menos de (-?\d+(?:\.\d+)?)$")
_HANDICAP_RE = re.compile(r"^(.*) ([+-]?\d+(?:\.\d+)?)$")
_H1_RE = re.compile(r'<h1 id="h1_partido">Apuestas (.+?) - (.+?)</h1>')
_START_RE = re.compile(r'data-date-utc="(\d+)"')


def _fmt_line(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _split_period(market_name: str) -> tuple[str, str]:
    """("1X2", "_HT") a partir de "1X2 - Primera mitad"; (nombre, "") si no hay mitad."""
    match = _PERIOD_RE.match(market_name)
    if not match:
        return market_name, ""
    return match.group(1), "_" + _PERIOD_SUFFIX[match.group(2)]


def _price(text: str) -> float | None:
    try:
        value = float(text.strip())
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


# El sitio identifica algunas casas con un `data-bookie` distinto del `name` que usa el
# proveedor DIRECTO de este repo para la misma casa (engine/quality.py:DIRECT_SOURCES):
# sin normalizar, engine/matching.py:best_odds_per_outcome las trataría como dos casas
# DISTINTAS en vez de una sola con dos lecturas - si algún ciclo llegan datos de ambas
# fuentes a la vez, podría fabricar una "surebet" entre "williamhill" y "william_hill",
# que en la realidad es la misma cuenta (no se puede apostar dos veces ahí). Comprobado
# en vivo el 2026-09-28 contra la caché real de la VM: de las 14 casas de DIRECT_SOURCES,
# solo estas dos difieren (el resto - betfair, bwin, sportium, versus, winamax, bet777,
# pokerstars, zebet, 888sport, kirolbet - ya coinciden tal cual).
_BOOKMAKER_ALIASES = {
    "william_hill": "williamhill",
    "marca_apuestas": "marcaapuestas",
}


def _canonical_bookie(bookie: str) -> str:
    return _BOOKMAKER_ALIASES.get(bookie, bookie)


class _Odd:
    __slots__ = ("mercado", "nombre", "bookie", "price")

    def __init__(self, mercado: str, nombre: str, bookie: str, price: float):
        self.mercado = mercado
        self.nombre = nombre
        self.bookie = bookie
        self.price = price


def _extract_odds(soup: BeautifulSoup) -> list[_Odd]:
    """Cada `.odd[data-mercado]` de la página es una tupla (mercado, resultado, casa,
    cuota) autocontenida - no hace falta entender la jerarquía del DOM alrededor, solo
    recorrerlas todas. Se descartan las marcadas `cuota_oculta` (vistas en "Marcador
    correcto": la cifra que traen no es la cuota real, ver docstring del módulo) por si
    algún mercado que sí procesamos llegara a usar la misma clase alguna vez."""
    odds: list[_Odd] = []
    for div in soup.select("div.odd[data-mercado]"):
        classes = div.get("class") or []
        if "cuota_oculta" in classes:
            continue
        bookie_div = div.select_one("[data-bookie]")
        mercado = div.get("data-mercado")
        nombre = div.get("data-nombre")
        if bookie_div is None or not mercado or nombre is None:
            continue
        span = div.find("span")
        price = _price(span.get_text() if span else div.get_text())
        if price is None:
            continue
        odds.append(_Odd(mercado, nombre, _canonical_bookie(bookie_div["data-bookie"]), price))
    return odds


def _outcome(name: str, bookie: str, price: float) -> Outcome:
    return Outcome(name=name, bookmaker=bookie, odds=price)


def _winner_market(event: str, sport: str, period: str, items: list[_Odd], home: str, away: str) -> list[Market]:
    label_of = {home: "1", away: "2", "Empate": "X"}
    outcomes = [_outcome(label_of[o.nombre], o.bookie, o.price) for o in items if o.nombre in label_of]
    if not outcomes:
        return []
    prefix = ("1X2" if any(o.name == "X" for o in outcomes) else "ML") + period
    return [Market(event=event, sport=sport, market_type=prefix, outcomes=outcomes)]


def _named_two_way(event: str, sport: str, market_type: str, items: list[_Odd], home: str, away: str) -> Market | None:
    label_of = {home: "1", away: "2"}
    outcomes = [_outcome(label_of[o.nombre], o.bookie, o.price) for o in items if o.nombre in label_of]
    return Market(event=event, sport=sport, market_type=market_type, outcomes=outcomes) if outcomes else None


def _yes_no_market(event: str, sport: str, market_type: str, items: list[_Odd]) -> Market | None:
    label_of = {"Sí": "Yes", "No": "No"}
    outcomes = [_outcome(label_of[o.nombre], o.bookie, o.price) for o in items if o.nombre in label_of]
    return Market(event=event, sport=sport, market_type=market_type, outcomes=outcomes) if outcomes else None


def _odd_even_market(event: str, sport: str, market_type: str, items: list[_Odd]) -> Market | None:
    label_of = {"Par": "Even", "Impar": "Odd"}
    outcomes = [_outcome(label_of[o.nombre], o.bookie, o.price) for o in items if o.nombre in label_of]
    return Market(event=event, sport=sport, market_type=market_type, outcomes=outcomes) if outcomes else None


def _dc_market(event: str, sport: str, market_type: str, items: list[_Odd], home: str, away: str) -> Market | None:
    outcomes = []
    for o in items:
        if o.nombre == f"{home} o Empate":
            label = "1X"
        elif o.nombre == f"{away} o Empate":
            label = "X2"
        elif o.nombre in (f"{home} o {away}", f"{away} o {home}"):
            label = "12"
        else:
            continue
        outcomes.append(_outcome(label, o.bookie, o.price))
    return Market(event=event, sport=sport, market_type=market_type, outcomes=outcomes) if outcomes else None


def _ou_markets(event: str, sport: str, prefix: str, items: list[_Odd]) -> list[Market]:
    by_line: dict[float, list[Outcome]] = {}
    for o in items:
        match = _OVER_RE.match(o.nombre)
        side = "Over"
        if not match:
            match = _UNDER_RE.match(o.nombre)
            side = "Under"
        if not match:
            continue
        line = float(match.group(1))
        by_line.setdefault(line, []).append(_outcome(side, o.bookie, o.price))
    return [
        Market(event=event, sport=sport, market_type=f"{prefix}_{_fmt_line(line)}", outcomes=outcomes)
        for line, outcomes in by_line.items()
    ]


def _ah_markets(event: str, sport: str, prefix: str, items: list[_Odd], home: str, away: str) -> list[Market]:
    by_line: dict[float, list[Outcome]] = {}
    for o in items:
        match = _HANDICAP_RE.match(o.nombre)
        if not match:
            continue
        team = match.group(1).strip()
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        # La línea se guarda siempre en perspectiva del local (mismo convenio que
        # providers/bet777.py): el visitante con "+2.5" es la misma línea que el local
        # con "-2.5", así que se invierte el signo para que ambos lados caigan en el
        # mismo `market_type` y puedan cruzar entre sí.
        if team == home:
            line = value
            label = "1"
        elif team == away:
            line = -value
            label = "2"
        else:
            continue
        by_line.setdefault(line, []).append(_outcome(label, o.bookie, o.price))
    return [
        Market(event=event, sport=sport, market_type=f"{prefix}_{_fmt_line(line)}", outcomes=outcomes)
        for line, outcomes in by_line.items()
    ]


def parse_event_markets(html: str, sport: str) -> list[Market]:
    """Convierte el HTML de `/cuotas/evento/<slug>/` en Markets. Sin `start_time`: lo
    rellena la propia clase del provider tras leer `data-date-utc` (ver `_fetch_event`),
    igual que `providers/bet777.py`."""
    h1 = _H1_RE.search(html)
    if not h1:
        return []
    home, away = h1.group(1).strip(), h1.group(2).strip()
    event_name = f"{home} vs. {away}"

    soup = BeautifulSoup(html, "html.parser")
    by_market: dict[str, list[_Odd]] = {}
    for odd in _extract_odds(soup):
        by_market.setdefault(odd.mercado, []).append(odd)

    markets: list[Market] = []
    for raw_market, items in by_market.items():
        base, period = _split_period(raw_market)
        if base in _WINNER_MARKETS:
            markets.extend(_winner_market(event_name, sport, period, items, home, away))
        elif base in _TWO_WAY_MARKETS:
            market = _named_two_way(event_name, sport, _TWO_WAY_MARKETS[base] + period, items, home, away)
            if market is not None:
                markets.append(market)
        elif base in _SET_WINNER_MARKETS:
            market = _named_two_way(event_name, sport, _SET_WINNER_MARKETS[base], items, home, away)
            if market is not None:
                markets.append(market)
        elif base in _YES_NO_MARKETS:
            market = _yes_no_market(event_name, sport, _YES_NO_MARKETS[base] + period, items)
            if market is not None:
                markets.append(market)
        elif base in _ODD_EVEN_MARKETS:
            market = _odd_even_market(event_name, sport, _ODD_EVEN_MARKETS[base] + period, items)
            if market is not None:
                markets.append(market)
        elif base in _DC_MARKETS:
            market = _dc_market(event_name, sport, _DC_MARKETS[base] + period, items, home, away)
            if market is not None:
                markets.append(market)
        elif base in _OU_MARKETS:
            markets.extend(_ou_markets(event_name, sport, _OU_MARKETS[base] + period, items))
        elif base in _AH_MARKETS:
            markets.extend(_ah_markets(event_name, sport, _AH_MARKETS[base] + period, items, home, away))
        # Cualquier otro nombre (Marcador correcto, Descanso/Final, Hándicap Europeo...)
        # se ignora a propósito, ver docstring del módulo.
    return markets


def _extract_start_time(html: str) -> datetime | None:
    match = _START_RE.search(html)
    if not match:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc)
    except (ValueError, OSError):
        return None


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.get(url)
        except httpx.TransportError as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 404:
            return None
        if response.status_code in (403, 429, 500, 502, 503, 504):
            last_error = RuntimeError(f"HTTP {response.status_code}")
            time.sleep(2.0 * (attempt + 1))
            continue
        response.raise_for_status()
        return response
    logger.warning("CasasDeApuestas: fallo de red en %s tras reintentos: %s", url, last_error)
    return None


def _decode_path(value: str) -> str | None:
    try:
        decoded = base64.b64decode(value).decode("utf-8")
    except Exception:
        return None
    return decoded.rstrip("/") if decoded.startswith("/cuotas/") else None


def discover_competitions(client: httpx.Client, section: str) -> list[str]:
    """Rutas de competición (p.ej. "/cuotas/futbol/espana/primera-division") de una
    sección de deporte, combinando el menú visible y el filtro de país oculto - ver
    docstring del módulo. Incluye siempre la propia raíz de la sección como "competición"
    de más (barato: si no lista partidos directamente, `discover_events` simplemente
    devuelve una lista vacía para ella)."""
    response = _get(client, f"{BASE}/cuotas/{section}/")
    if response is None:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    paths: set[str] = {f"/cuotas/{section}"}

    prefix = f"/cuotas/{section}/"
    for a in soup.select(f'a[href*="{prefix}"]'):
        href = a.get("href", "")
        idx = href.find(prefix)
        if idx == -1:
            continue
        path = "/" + href[idx:].strip("/")
        parts = path.strip("/").split("/")
        if len(parts) >= 4:  # cuotas/<seccion>/<pais>/<liga>
            paths.add(path)

    for el in soup.select("[data-league-id]"):
        decoded = _decode_path(el.get("data-league-id", ""))
        if decoded and decoded.startswith(prefix.rstrip("/")):
            paths.add(decoded)

    return sorted(paths)


def discover_events(client: httpx.Client, competition_path: str) -> list[str]:
    """Rutas de partido (p.ej. "/cuotas/evento/malaga-espanyol-540966") listados en la
    página de una competición."""
    response = _get(client, f"{BASE}{competition_path}/")
    if response is None:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    paths: list[str] = []
    for el in soup.select(".event-teams [data-lnk]"):
        decoded = _decode_path(el.get("data-lnk", ""))
        if decoded and decoded.startswith("/cuotas/evento/"):
            paths.append(decoded)
    return paths


class CasasDeApuestasProvider(OddsProvider):
    """casasdeapuestas.com: comparador multi-casa por HTML plano, sin navegador. Ver
    docstring del módulo para el vocabulario de mercados y por qué va en
    `comparator_providers()` pese a no usar Playwright."""

    name = "casasdeapuestas"
    fast_recheck = True

    def __init__(
        self,
        horizon_hours: int | None = None,
        max_matches: int | None = None,
        max_workers: int = 5,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.horizon_hours = horizon_hours or int(
            os.environ.get("CASASDEAPUESTAS_HORIZON_HOURS", DEFAULT_HORIZON_HOURS)
        )
        # Tope de partidos leídos por competición (los primeros del listado). 0/None =
        # sin tope - hay competiciones (NFL, tenis) con decenas de partidos listados.
        self.max_matches = (
            max_matches if max_matches is not None else int(os.environ.get("CASASDEAPUESTAS_MAX_MATCHES", "0")) or None
        )
        self.max_workers = max_workers
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        # Mismo truco que providers/bet777.py: "baloncesto_nba"/"tenis_atp"/etc. (claves
        # compuestas que usa CuotasAhora) colapsan a su deporte base, que es lo único que
        # necesitamos - este provider descubre las competiciones solo, no por clave.
        requested = {key.split("_", 1)[0] for key in sports} & set(SPORT_SECTIONS)
        if not requested:
            return []
        with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            markets: list[Market] = []
            for sport in requested:
                markets.extend(self._fetch_sport(client, sport))
            return markets

    def _fetch_sport(self, client: httpx.Client, sport: str) -> list[Market]:
        section = SPORT_SECTIONS[sport]
        competitions = discover_competitions(client, section)
        logger.info("CasasDeApuestas: %d competiciones descubiertas en %s", len(competitions), section)
        if not competitions:
            return []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            per_competition = list(pool.map(lambda path: discover_events(client, path), competitions))

        events: list[tuple[str, str]] = []
        for comp_path, slugs in zip(competitions, per_competition):
            if self.max_matches:
                slugs = slugs[: self.max_matches]
            events.extend((slug, comp_path) for slug in slugs)
        logger.info(
            "CasasDeApuestas: %d partidos de %s en %d competiciones", len(events), sport, len(competitions)
        )
        if not events:
            return []

        def fetch(item: tuple[str, str]) -> list[Market]:
            path, comp_label = item
            try:
                return self._fetch_event(client, sport, path, comp_label)
            except Exception:  # un partido con formato raro no debe tumbar a los demás
                logger.warning("CasasDeApuestas: fallo en %s", path, exc_info=True)
                return []

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for result in pool.map(fetch, events):
                markets.extend(result)
        return markets

    def cache_units(self, sports: list[str]) -> list[tuple[str, Callable[[], list[Market]]]]:
        """Para el ciclo lento (engine/cache.py): una unidad de caché por competición
        descubierta, no una por deporte entero. `_fetch_sport` (arriba, usado por
        `fetch_markets` en los modos `full`/`fast` en vivo) lee TODO un deporte de golpe
        - bien para esos modos, pero mal para el ciclo lento, que reparte un presupuesto
        de tiempo fijo entre muchas unidades pequeñas (así funcionaba CuotasAhora, una
        liga cada vez): un solo deporte grande (fútbol, ~100 competiciones) se comería
        el presupuesto entero de una sentada y dejaría sin refrescar todo lo demás.

        Descubrir las competiciones de cada deporte pedido es barato (una petición por
        deporte, ver `discover_competitions`) y se hace aquí, de una sola vez para las
        `sports` pedidas - cada unidad devuelta ya sabe qué competición concreta le
        toca, así que engine/cache.py puede rotarlas una a una como si fueran ligas de
        CuotasAhora. La clave de caché lleva el deporte delante ("futbol::/cuotas/...")
        porque la competición sola no basta para saber a qué deporte pertenece.
        """
        requested = {key.split("_", 1)[0] for key in sports} & set(SPORT_SECTIONS)
        if not requested:
            return []
        units: list[tuple[str, Callable[[], list[Market]]]] = []
        with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            for sport in sorted(requested):
                section = SPORT_SECTIONS[sport]
                for comp_path in discover_competitions(client, section):
                    units.append((f"{sport}::{comp_path}", self._competition_fetcher(sport, comp_path)))
        return units

    def _competition_fetcher(self, sport: str, comp_path: str) -> Callable[[], list[Market]]:
        def fetch() -> list[Market]:
            with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
                return self._fetch_competition(client, sport, comp_path)

        return fetch

    def _fetch_competition(self, client: httpx.Client, sport: str, comp_path: str) -> list[Market]:
        slugs = discover_events(client, comp_path)
        if self.max_matches:
            slugs = slugs[: self.max_matches]
        if not slugs:
            return []

        def fetch(path: str) -> list[Market]:
            try:
                return self._fetch_event(client, sport, path, comp_path)
            except Exception:
                logger.warning("CasasDeApuestas: fallo en %s", path, exc_info=True)
                return []

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for result in pool.map(fetch, slugs):
                markets.extend(result)
        return markets

    def _fetch_event(self, client: httpx.Client, sport: str, path: str, competition_label: str) -> list[Market]:
        response = _get(client, f"{BASE}{path}/")
        if response is None:
            return []
        html = response.text
        h1 = _H1_RE.search(html)
        if not h1:
            return []
        home, away = h1.group(1).strip(), h1.group(2).strip()
        if is_excluded([competition_label, home, away], self.exclude_esports, self.exclude_women, sport=sport):
            return []

        start = _extract_start_time(html)
        if start is not None:
            now = datetime.now(timezone.utc)
            if not (now < start <= now + timedelta(hours=self.horizon_hours)):
                return []

        markets = parse_event_markets(html, sport)
        for market in markets:
            market.start_time = start
        return markets
