import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.altenar import _fmt_line
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

# Página ligera del mismo origen desde la que se abre el socket (la web real
# tarda 10-25 s en cargar por sus trackers y su cliente no siempre conecta).
HOST_PAGE = "https://www.winamax.es/robots.txt"
FALLBACK_HOST_PAGE = "https://www.winamax.es/apuestas-deportivas/"
ATTEMPTS = 2

# Clave de competición del sistema -> "<categoría>/<torneo>" de Winamax (fútbol es
# el deporte 1). Identificadores tomados de `PRELOADED_STATE.tournaments` el
# 2026-09-21. Las claves sin entrada aquí no se leen en Winamax.
COMPETITIONS: dict[str, str] = {
    "futbol": "32/36",  # LaLiga
    "futbol_champions": "800000542/151665",
    "futbol_premier": "1/1",
    "futbol_seriea": "31/33",
    "futbol_bundesliga": "30/42",
    "futbol_ligue1": "7/4",
    "futbol_europa_league": "800000542/10909",
    "futbol_conference_league": "800000542/151677",
    "futbol_copa_rey": "32/150",
    "futbol_eredivisie": "35/39",
    "futbol_liga_portugal": "44/52",
    "futbol_championship": "1/2",
    "futbol_jupiler": "33/38",
    "futbol_brasileirao": "13/83",
    "futbol_liga_mx": "12/28",
    "futbol_scotland": "22/54",
    "futbol_libertadores": "4/900002339",
    "futbol_sudamericana": "4/99936",
    "futbol_austria": "17/29",
    "futbol_dinamarca": "8/12",
    "futbol_polonia": "47/64",
    "futbol_noruega": "5/5",
    "futbol_suecia": "9/24",
}

# Cada competición cuesta ~2 s (listado) más ~1,5 s por partido leído: se leen todas.
DEFAULT_KEYS = tuple(COMPETITIONS)

# Cliente del socket que usa la propia web de Winamax (socket.io v3): tras conectar,
# `42["m",{"route":"tournament:<id>"}]` devuelve los partidos de una competición y
# `route: "match:<id>"` la ficha completa de un partido (~100 mercados), en varios
# mensajes seguidos (primero los 5 principales, luego el resto): se fusionan hasta
# que el flujo se calma. Varios sockets en paralelo se reparten la lista de rutas.
_SOCKET_JS = """async ({routes, concurrency, quietMs, maxMs}) => {
    const URL = 'wss://sports-eu-west-3.winamax.es/uof-sports-server/socket.io/?language=ES&version=3.65.0&embed=false&EIO=3&transport=websocket';
    const KEYS = ['matches', 'bets', 'outcomes', 'odds', 'tournaments'];
    const out = {};
    let next = 0;
    const worker = () => new Promise((done) => {
        const ws = new WebSocket(URL);
        let route = null, acc = null, lastData = 0, startedAt = 0, ready = false;
        const opened = Date.now();
        const finish = () => {
            if (route !== null) { out[route] = acc && (acc.bets || acc.matches) ? acc : null; route = null; }
        };
        const take = () => {
            if (next >= routes.length) { clearInterval(timer); try { ws.close(); } catch (e) {} done(); return; }
            route = routes[next++];
            acc = {}; lastData = 0; startedAt = Date.now();
            ws.send('42' + JSON.stringify(['m', {route, requestId: 'q' + next}]));
        };
        const timer = setInterval(() => {
            const now = Date.now();
            if (!ready) { if (now - opened > 8000) { clearInterval(timer); try { ws.close(); } catch (e) {} done(); } return; }
            if (route === null) return;
            if ((lastData && now - lastData > quietMs) || now - startedAt > maxMs) { finish(); take(); }
        }, 100);
        ws.onerror = () => { if (!ready) { clearInterval(timer); done(); } };
        ws.onclose = () => { if (route !== null) { finish(); } clearInterval(timer); done(); };
        ws.onmessage = (event) => {
            const data = event.data;
            if (data === '2') { ws.send('3'); return; }
            if (data === '40') { ready = true; take(); return; }
            if (!data.startsWith('42') || route === null) return;
            let payload;
            try { payload = JSON.parse(data.slice(2))[1]; } catch (e) { return; }
            if (!payload || !(payload.bets || payload.matches)) return;
            for (const key of KEYS) { if (payload[key]) acc[key] = Object.assign(acc[key] || {}, payload[key]); }
            lastData = Date.now();
        };
    });
    await Promise.all(Array.from({length: concurrency}, worker));
    return out;
}"""

_HALF_RE = re.compile(r"^\s*(1|2)\s*[ªº°]\s*mitad\s*-\s*", re.IGNORECASE)
_LINE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*$")
_NUMBER_RE = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*$")


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _pairs(state: dict, bet: dict) -> list[tuple[str, str, float]] | None:
    """(etiqueta, código, cuota) de cada selección de la apuesta, o None si alguna
    no está disponible (un mercado incompleto no vale para arbitraje)."""
    out = []
    for outcome_id in bet.get("outcomes", []):
        outcome = state["outcomes"].get(str(outcome_id))
        odd = state["odds"].get(str(outcome_id))
        if outcome is None or odd is None or not outcome.get("available") or not bet.get("available"):
            return None
        price = float(odd)
        if price <= 1.0:
            return None
        out.append((outcome["label"].strip(), str(outcome.get("code")), price))
    return out or None


def _emit(event, bookmaker, market_type, pairs, expected) -> Market | None:
    labels = [label for label, _ in pairs]
    if None in labels or set(labels) != expected or len(labels) != len(expected):
        return None
    return Market(
        event=event,
        sport="futbol",
        market_type=market_type,
        outcomes=[Outcome(name=label, bookmaker=bookmaker, odds=price) for label, price in pairs],
    )


def _team_of(title: str, home: str, away: str) -> str | None:
    """"_HOME"/"_AWAY" según el nombre de equipo que aparece en el título."""
    has_home, has_away = home.lower() in title.lower(), away.lower() in title.lower()
    if has_home == has_away:
        return None
    return "_HOME" if has_home else "_AWAY"


def parse_match_state(state: dict, match_id, bookmaker: str = "winamax") -> list[Market]:
    """Convierte el `PRELOADED_STATE` de la ficha de un partido en Markets.

    Los títulos de Winamax usan el nombre corto de cada equipo ("Atl. Madrid"), que
    se toma de las selecciones 1 y 2 del mercado "Resultado" (por su código, no
    por su texto). Los resultados se identifican por el `code` de cada selección
    (1/x/2, 74=Sí, 76=No, 70=Impar, 72=Par, over/under...). Solo se emiten
    mercados de resultados excluyentes y exhaustivos, con los mismos prefijos que
    Altenar/Kambi/los comparadores.
    """
    match = state["matches"].get(str(match_id))
    if match is None or match.get("status") != "PREMATCH" or not match.get("available"):
        return []
    event = f"{match['competitor1Name'].strip()} vs. {match['competitor2Name'].strip()}"
    start = datetime.fromtimestamp(match["matchStart"], tz=timezone.utc)
    bets = [b for b in state["bets"].values() if b.get("matchId") == match["matchId"]]

    # nombres cortos de los equipos, a partir del mercado principal "Resultado"
    home = away = None
    for bet in bets:
        if bet["betTitle"].strip().lower() == "resultado":
            pairs = _pairs(state, bet)
            codes = {code: label for label, code, _ in pairs or []}
            home, away = codes.get("1"), codes.get("2")
            break
    if not home or not away:
        home, away = match["competitor1Name"], match["competitor2Name"]

    built: dict[str, Market] = {}

    def add(market: Market | None) -> None:
        if market is not None and market.market_type not in built:
            market.start_time = start
            built[market.market_type] = market

    for bet in bets:
        pairs = _pairs(state, bet)
        if pairs is None:
            continue
        title = bet["betTitle"].strip()
        half = _HALF_RE.match(title)
        suffix = {"1": "_HT", "2": "_2H"}[half.group(1)] if half else ""
        body = title[half.end():] if half else title
        low = body.lower()
        by_code = {code: price for _, code, price in pairs}

        def coded(mapping):
            return [(mapping.get(code), price) for _, code, price in pairs]

        if low == "resultado":
            add(_emit(event, bookmaker, f"1X2{suffix}", coded({"1": "1", "x": "X", "2": "2"}), {"1", "X", "2"}))
        elif low.startswith("ganador sin empate"):
            add(_emit(event, bookmaker, f"DNB{suffix}", coded({"1": "1", "2": "2"}), {"1", "2"}))
        elif low == "doble oportunidad":
            add(_emit(event, bookmaker, f"DC{suffix}", coded({"9": "1X", "10": "12", "11": "X2"}), {"1X", "12", "X2"}))
        elif low == "ambos equipos marcan":
            add(_emit(event, bookmaker, f"BTTS{suffix}", coded({"74": "Yes", "76": "No"}), {"Yes", "No"}))
        elif low == "total de goles - par/impar":
            add(_emit(event, bookmaker, f"OE{suffix}", coded({"70": "Odd", "72": "Even"}), {"Odd", "Even"}))
        elif low.startswith("total de goles marcados por") and low.endswith("par/impar"):
            team = _team_of(body, home, away)
            if team:
                add(_emit(event, bookmaker, f"OE{team}{suffix}", coded({"70": "Odd", "72": "Even"}), {"Odd", "Even"}))
        elif low == "equipo que marca el 1er gol":
            add(_emit(event, bookmaker, f"FIRST_GOAL{suffix}", coded({"6": "1", "7": "None", "8": "2"}), {"1", "None", "2"}))
        elif low == "equipo que marca el último gol":
            add(_emit(event, bookmaker, f"LAST_GOAL{suffix}", coded({"6": "1", "7": "None", "8": "2"}), {"1", "None", "2"}))
        elif re.match(r"^n[úu]mero total de goles(?! exactos)", low) and "over" in by_code and "under" in by_code:
            # "Número total de goles" (partido), "... marcados por X", "... de X", "... por X"
            rest = re.sub(r"^n[úu]mero total de goles", "", low, flags=re.IGNORECASE).strip()
            team = ""
            if rest:
                if not re.match(r"^(marcados por|de|por)\s", rest):
                    continue
                team = _team_of(body, home, away)
                if not team:
                    continue
            over = next((label for label, code, _ in pairs if code == "over"), "")
            match_line = _LINE_RE.search(over)
            if match_line:
                line = _num(match_line.group(1))
                pair = [("Over" if code == "over" else "Under" if code == "under" else None, price) for _, code, price in pairs]
                add(_emit(event, bookmaker, f"OU{team}{suffix}_{_fmt_line(line)}", pair, {"Over", "Under"}))
        elif low.startswith("hándicap asiático"):
            sides = {}
            for label, _code, price in pairs:
                number = _NUMBER_RE.search(label)
                team = _team_of(label, home, away)
                if number and team:
                    sides["1" if team == "_HOME" else "2"] = (_num(number.group(1)), price)
            if set(sides) == {"1", "2"} and sides["1"][0] == -sides["2"][0]:
                line = sides["1"][0]
                add(_emit(event, bookmaker, f"AH{suffix}_{_fmt_line(line, signed=True)}", [("1", sides["1"][1]), ("2", sides["2"][1])], {"1", "2"}))
    return list(built.values())


class WinamaxProvider(OddsProvider):
    """Winamax.es por el socket (socket.io) que usa su propia web, abierto desde una
    página de su mismo origen en un navegador (Playwright).

    Una petición HTTP suelta recibe 403 de su protección anti-bot (no se intenta
    esquivar) y la web completa tarda 10-25 s en cargar y no siempre conecta su
    cliente, así que se habla directamente el protocolo del socket: una ruta por
    competición (`tournament:<id>`, solo el mercado principal de cada partido) y una
    por partido (`match:<id>`, ~100 mercados). Solo pre-partido, dentro del horizonte
    y con un tope de partidos por competición.
    """

    name = "winamax"
    fast_recheck = False

    def __init__(
        self,
        competitions: dict[str, str] | None = None,
        keys: tuple[str, ...] | None = None,
        horizon_hours: int | None = None,
        max_matches: int | None = None,
        concurrency: int = 4,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.competitions = competitions or COMPETITIONS
        self.keys = keys or DEFAULT_KEYS
        self.horizon = timedelta(hours=horizon_hours or int(os.environ.get("WINAMAX_HORIZON_HOURS", 96)))
        self.max_matches = max_matches or int(os.environ.get("WINAMAX_MAX_MATCHES", "12"))
        self.concurrency = concurrency
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        wanted = [key for key in self.keys if key in sports and key in self.competitions]
        if not wanted:
            return []
        return asyncio.run(self._fetch_async(wanted))

    async def _socket(self, page, routes: list[str], concurrency: int, quiet_ms: int, max_ms: int) -> dict:
        """{ruta: estado} de las rutas pedidas; una ruta que no respondió queda en None
        o ausente y se reintenta una vez."""
        results: dict = {}
        pending = list(routes)
        for _ in range(ATTEMPTS):
            if not pending:
                break
            got = await page.evaluate(
                _SOCKET_JS, {"routes": pending, "concurrency": concurrency, "quietMs": quiet_ms, "maxMs": max_ms}
            )
            results.update({route: state for route, state in got.items() if state})
            pending = [route for route in pending if route not in results]
        if pending:
            logger.warning("Winamax: %d rutas sin respuesta (p.ej. %s)", len(pending), pending[0])
        return results

    async def _fetch_async(self, keys: list[str]) -> list[Market]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(HOST_PAGE, timeout=30000, wait_until="domcontentloaded")
                routes = [f"tournament:{self.competitions[key].split('/')[-1]}" for key in keys]
                listings = await self._socket(page, routes, self.concurrency, 500, 8000)
                if not listings:  # el origen ligero no sirvió: se prueba desde la web real
                    await page.goto(FALLBACK_HOST_PAGE, timeout=40000, wait_until="domcontentloaded")
                    listings = await self._socket(page, routes, self.concurrency, 500, 8000)
                ids: list[int] = []
                for key in keys:
                    tournament = self.competitions[key].split("/")[-1]
                    listing = listings.get(f"tournament:{tournament}")
                    chosen = self._select(listing) if listing else []
                    logger.info("Winamax %s: %d partidos a leer", key, len(chosen))
                    ids.extend(chosen)
                states = await self._socket(page, [f"match:{i}" for i in ids], self.concurrency, 700, 10000)
            finally:
                await browser.close()
        markets: list[Market] = []
        for match_id in ids:
            state = states.get(f"match:{match_id}")
            if state:
                markets.extend(parse_match_state(state, match_id, self.name))
        return markets

    def _select(self, listing: dict) -> list[int]:
        now = datetime.now(timezone.utc)
        chosen = []
        for match in sorted(listing["matches"].values(), key=lambda m: m.get("matchStart", 0)):
            if match.get("status") != "PREMATCH" or not match.get("available") or match.get("sportId") != 1:
                continue
            start = datetime.fromtimestamp(match["matchStart"], tz=timezone.utc)
            if not (now < start <= now + self.horizon):
                continue
            if is_excluded([match.get("title"), match.get("competitor1Name"), match.get("competitor2Name")], self.exclude_esports, self.exclude_women):
                continue
            chosen.append(match["matchId"])
        return chosen[: self.max_matches]
