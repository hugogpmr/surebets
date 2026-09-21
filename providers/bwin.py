import asyncio
import logging
import math
import os
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.altenar import DEFAULT_HORIZON_HOURS, _fmt_line
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

LOBBY_URL = "https://sports.bwin.es/es/sports/f%C3%BAtbol-4"
API_BASE = "https://www.bwin.es/cds-api/bettingoffer/"
# Clave pública que el propio front de bwin manda en cada petición a su API
# (`x-bwin-accessid`, visible en cualquier petición de la web; no es una
# credencial de usuario).
ACCESS_ID = "OTdhMjU3MWQtYzI5Yi00NWQ5LWFmOGEtNmFhOTJjMWVhNmRl"
COMMON = f"x-bwin-accessid={ACCESS_ID}&lang=es&country=ES&userCountry=ES"
FOOTBALL_SPORT_ID = 4

# Solo se piden las fichas de partidos con al menos estos mercados (los de
# ligas menores traen 14-18 y casi nunca cruzan con otras casas).
MIN_MARKETS = 20

# Petición a la API DESDE la página ya cargada de bwin: es exactamente lo que hace
# su propio front (con sus cookies de sesión) y es lo que funciona; una petición
# HTTP suelta recibe 403 de su protección anti-bot, que no se intenta esquivar.
_FETCH_MANY_JS = """async ({items, concurrency}) => {
    const out = {};
    let next = 0;
    async function worker() {
        while (next < items.length) {
            const item = items[next++];
            try {
                const response = await fetch(item.url, {credentials: 'include'});
                out[item.id] = response.ok ? await response.json() : {error: response.status};
            } catch (error) {
                out[item.id] = {error: String(error)};
            }
        }
    }
    await Promise.all(Array.from({length: concurrency}, worker));
    return out;
}"""

_PERIOD_SUFFIX = {"RegularTime": "", "FirstHalf": "_HT", "SecondHalf": "_2H"}
_HAPPENING_PREFIX = {"Goal": "", "Corner": "CORNERS_", "CombinedCards": "CARDS_"}

_YES_NO = {"sí": "Yes", "si": "Yes", "no": "No"}
_ODD_EVEN = {"impar": "Odd", "par": "Even"}


def _display_price(price: float) -> float:
    return math.floor(price * 100 + 0.5) / 100


def _params(market: dict) -> dict:
    return {p["key"]: p["value"] for p in market.get("parameters", [])}


def _team_side(participant_id, home_id, away_id) -> str | None:
    if participant_id is None:
        return None
    participant_id = int(participant_id)
    if participant_id == home_id:
        return "1"
    if participant_id == away_id:
        return "2"
    return None


def _open_options(market: dict) -> list[dict] | None:
    """Selecciones del mercado o None si alguna no está abierta o sin cuota: un
    mercado con una selección retirada no es completo y no vale para arbitraje."""
    options = market.get("options", [])
    if not options or any(o.get("status") != "Visible" or (o.get("price") or {}).get("odds") is None for o in options):
        return None
    return options


def _price(option: dict) -> float | None:
    value = _display_price(float(option["price"]["odds"]))
    return value if value > 1.0 else None


def _labelled(option: dict, home_id, away_id) -> str | None:
    """Etiqueta 1/X/2 de una selección de tres resultados (equipos por su id, el
    empate por su tipo), sin depender de su texto."""
    params = option.get("parameters") or {}
    side = _team_side(params.get("fixtureParticipant"), home_id, away_id)
    if side:
        return side
    return "X" if "Draw" in (params.get("optionTypes") or []) else None


def _market(event, bookmaker, market_type, pairs, expected) -> Market | None:
    """`pairs` = [(etiqueta, cuota)]. Solo se emite si las etiquetas son
    exactamente las esperadas: un resultado desconocido significa que el mercado
    no es el que creemos y un conjunto incompleto fabricaría un arbitraje falso."""
    labels = [label for label, _ in pairs]
    if None in labels or set(labels) != expected or len(labels) != len(expected):
        return None
    if any(price is None for _, price in pairs):
        return None
    return Market(
        event=event,
        sport="futbol",
        market_type=market_type,
        outcomes=[Outcome(name=label, bookmaker=bookmaker, odds=price) for label, price in pairs],
    )


def _handicap_line(option: dict, participant_name: str) -> float | None:
    """Línea de un resultado de hándicap a partir de su texto ("Equipo (-0,5)")."""
    name = option["name"]["value"].strip()
    if not name.endswith(")") or "(" not in name:
        return None
    try:
        return float(name[name.rindex("(") + 1 : -1].replace(",", "."))
    except ValueError:
        return None


def parse_fixture(view: dict, bookmaker: str = "bwin") -> list[Market]:
    """Convierte la ficha completa de un partido (`fixture-view`) en Markets.

    Los mercados se reconocen por sus parámetros estructurados (`MarketType`,
    `Happening`, `Period`, línea...), no por el texto en español. Solo se emiten
    mercados de resultados excluyentes y exhaustivos, con los mismos prefijos de
    market_type que Altenar/Kambi/los comparadores. Quedan fuera los mercados con
    `MarketSubType` o `RangeValue` (variantes especiales: "resultado al minuto 60",
    y sobre todo el "Resultado VA (+2)", que paga por adelantado si un equipo va 2
    goles arriba y NO es un 1X2 normal).
    """
    fixture = view.get("fixture", view)
    teams = {p["properties"]["type"]: p for p in fixture.get("participants", []) if p.get("properties", {}).get("type") in ("HomeTeam", "AwayTeam")}
    if "HomeTeam" not in teams or "AwayTeam" not in teams:
        return []
    home, away = teams["HomeTeam"], teams["AwayTeam"]
    home_id, away_id = home["id"], away["id"]
    home_name, away_name = home["name"]["value"].strip(), away["name"]["value"].strip()
    event = f"{home_name} vs. {away_name}"
    start = datetime.fromisoformat(fixture["startDate"].replace("Z", "+00:00"))

    built: dict[str, Market] = {}
    for raw in fixture.get("optionMarkets", []):
        if raw.get("status") != "Visible":
            continue
        p = _params(raw)
        if p.get("MarketSubType") or p.get("RangeValue"):
            continue
        prefix = _HAPPENING_PREFIX.get(p.get("Happening"))
        suffix = _PERIOD_SUFFIX.get(p.get("Period"))
        options = _open_options(raw)
        if prefix is None or suffix is None or options is None:
            continue
        kind = p.get("MarketType")
        market = None

        if kind == "3way":
            pairs = [(_labelled(o, home_id, away_id), _price(o)) for o in options]
            market = _market(event, bookmaker, f"{prefix}1X2{suffix}", pairs, {"1", "X", "2"})
        elif kind == "DrawNoBet" and prefix == "":
            pairs = [(_team_side((o.get("parameters") or {}).get("fixtureParticipant"), home_id, away_id), _price(o)) for o in options]
            market = _market(event, bookmaker, f"DNB{suffix}", pairs, {"1", "2"})
        elif kind == "DoubleChance" and prefix == "":
            pairs = []
            for o in options:
                # "Local o X" -> {1, X}; el texto solo se usa para ordenar la etiqueta
                text = o["name"]["value"]
                for name, tag in sorted(((home_name, "1"), (away_name, "2")), key=lambda x: -len(x[0])):
                    text = text.replace(name, tag)
                parts = {t.strip().upper() for t in text.split(" o ")}
                label = {frozenset({"1", "X"}): "1X", frozenset({"X", "2"}): "X2", frozenset({"1", "2"}): "12"}.get(frozenset(parts))
                pairs.append((label, _price(o)))
            market = _market(event, bookmaker, f"DC{suffix}", pairs, {"1X", "12", "X2"})
        elif kind == "BTTS" and prefix == "":
            pairs = [(_YES_NO.get(o["name"]["value"].strip().lower()), _price(o)) for o in options]
            market = _market(event, bookmaker, f"BTTS{suffix}", pairs, {"Yes", "No"})
        elif kind == "Odd/Even":
            side = _team_side(p.get("FixtureParticipant"), home_id, away_id)
            team = {"1": "_HOME", "2": "_AWAY"}.get(side, "")
            if p.get("FixtureParticipant") and not team:
                continue
            pairs = [(_ODD_EVEN.get(o["name"]["value"].strip().lower()), _price(o)) for o in options]
            market = _market(event, bookmaker, f"{prefix}OE{team}{suffix}", pairs, {"Odd", "Even"})
        elif kind == "Over/Under":
            side = _team_side(p.get("FixtureParticipant"), home_id, away_id)
            team = {"1": "_HOME", "2": "_AWAY"}.get(side, "")
            if p.get("FixtureParticipant") and not team:
                continue
            try:
                line = float(p["DecimalValue"])
            except (KeyError, ValueError):
                continue
            pairs = []
            for o in options:
                types = (o.get("parameters") or {}).get("optionTypes") or []
                pairs.append(("Over" if "Over" in types else "Under" if "Under" in types else None, _price(o)))
            market = _market(event, bookmaker, f"{prefix}OU{team}{suffix}_{_fmt_line(line)}", pairs, {"Over", "Under"})
        elif kind == "2wayHandicap":
            by_side = {}
            for o in options:
                side = _team_side((o.get("parameters") or {}).get("fixtureParticipant"), home_id, away_id)
                line = _handicap_line(o, home_name if side == "1" else away_name)
                if side and line is not None:
                    by_side[side] = (line, _price(o))
            # ambos lados deben describir la misma línea expresada desde el local
            if set(by_side) == {"1", "2"} and by_side["1"][0] == -by_side["2"][0]:
                line = by_side["1"][0]
                market = _market(
                    event, bookmaker, f"{prefix}AH{suffix}_{_fmt_line(line, signed=True)}",
                    [("1", by_side["1"][1]), ("2", by_side["2"][1])], {"1", "2"},
                )
        elif kind == "XthHappening" and p.get("IntegerValue") == "1" and prefix in ("", "CORNERS_"):
            pairs = []
            for o in options:
                side = _team_side((o.get("parameters") or {}).get("fixtureParticipant"), home_id, away_id)
                pairs.append((side or "None", _price(o)))
            market = _market(event, bookmaker, f"{prefix}FIRST{'_GOAL' if prefix == '' else ''}{suffix}", pairs, {"1", "None", "2"})

        if market is not None and market.market_type not in built:
            market.start_time = start
            built[market.market_type] = market
    return list(built.values())


def select_fixtures(fixtures: list[dict], now: datetime, horizon: timedelta, exclude_esports: bool, exclude_women: bool) -> list[dict]:
    """Partidos pre-partido (no en juego ni virtuales) dentro del horizonte, con
    suficientes mercados, sin fútbol virtual/femenino (ver providers/filters.py)."""
    selected = []
    for fixture in fixtures:
        if fixture.get("stage") == "Live" or fixture.get("isVirtual") or fixture.get("totalMarketsCount", 0) < MIN_MARKETS:
            continue
        start = datetime.fromisoformat(fixture["startDate"].replace("Z", "+00:00"))
        if not (now < start <= now + horizon):
            continue
        labels = [
            fixture.get("name", {}).get("value"),
            fixture.get("competition", {}).get("name", {}).get("value"),
            fixture.get("region", {}).get("name", {}).get("value"),
        ]
        if is_excluded(labels, exclude_esports, exclude_women):
            continue
        selected.append(fixture)
    return selected


class BwinProvider(OddsProvider):
    """bwin.es (Entain) por el API JSON de ofertas de su propio front, leída
    desde el navegador con la página ya cargada (ver _FETCH_MANY_JS).

    Fuente DIRECTA de la casa con cientos de mercados por partido, incluidos córners
    y tarjetas (que no existen en los comparadores). Los mercados llegan con
    parámetros estructurados, así que no se depende del texto. Solo pre-partido:
    los partidos en juego y el fútbol virtual se descartan.
    """

    name = "bwin"
    fast_recheck = False  # necesita navegador: una segunda lectura cuesta ~1 min

    def __init__(
        self,
        horizon_hours: int | None = None,
        concurrency: int = 4,
        batch_size: int = 30,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.horizon = timedelta(hours=horizon_hours or int(os.environ.get("BWIN_HORIZON_HOURS", DEFAULT_HORIZON_HOURS)))
        self.concurrency = concurrency
        self.batch_size = batch_size
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        return asyncio.run(self._fetch_async())

    async def _fetch_async(self) -> list[Market]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(LOBBY_URL, timeout=40000)
                await page.wait_for_timeout(3000)
                fixtures = await self._list_fixtures(page)
                chosen = select_fixtures(
                    fixtures, datetime.now(timezone.utc), self.horizon, self.exclude_esports, self.exclude_women
                )
                logger.info("bwin: %d partidos en el listado, %d a leer", len(fixtures), len(chosen))
                markets: list[Market] = []
                for i in range(0, len(chosen), self.batch_size):
                    markets.extend(await self._read_batch(page, chosen[i : i + self.batch_size]))
                return markets
            finally:
                await browser.close()

    async def _list_fixtures(self, page) -> list[dict]:
        fixtures: list[dict] = []
        skip, take = 0, 500
        while True:
            url = (
                f"{API_BASE}fixtures?{COMMON}&fixtureTypes=Standard&state=Latest&offerMapping=None"
                f"&offerCategories=Gridable&fixtureCategories=Gridable,NonGridable,Specials,Tournaments,Games"
                f"&sportIds={FOOTBALL_SPORT_ID}&skip={skip}&take={take}&sortBy=StartDate"
            )
            result = await page.evaluate(_FETCH_MANY_JS, {"items": [{"id": "list", "url": url}], "concurrency": 1})
            data = result["list"]
            if "error" in data:
                raise RuntimeError(f"bwin: listado de partidos rechazado ({data['error']})")
            fixtures.extend(data.get("fixtures", []))
            skip += take
            if skip >= data.get("totalCount", 0) or not data.get("fixtures"):
                return fixtures

    async def _read_batch(self, page, batch: list[dict]) -> list[Market]:
        items = [
            {
                "id": f["id"],
                "url": (
                    f"{API_BASE}fixture-view?{COMMON}&offerMapping=All&scoreboardMode=Full&fixtureIds={f['id']}"
                    "&state=Latest&includePrecreatedBetBuilder=true&supportVirtual=false"
                    "&useRegionalisedConfiguration=true&includeRelatedFixtures=false"
                ),
            }
            for f in batch
        ]
        results = await page.evaluate(_FETCH_MANY_JS, {"items": items, "concurrency": self.concurrency})
        markets: list[Market] = []
        for item in items:
            view = results.get(item["id"], {})
            if "error" in view:
                logger.warning("bwin: fallo leyendo %s (%s)", item["id"], view["error"])
                continue
            markets.extend(parse_fixture(view, self.name))
        return markets
