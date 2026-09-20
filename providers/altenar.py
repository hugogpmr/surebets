import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from engine.models import Market, Outcome
from providers.base import OddsProvider

logger = logging.getLogger(__name__)

API_BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget/"
COMMON_PARAMS = {
    "culture": "es-ES",
    "timezoneOffset": "-120",
    "deviceType": "1",
    "numFormat": "en-GB",
    "countryCode": "ES",
}

# Casas que usan la plataforma de apuestas Altenar (mismo motor, misma API
# pública sin autenticación que consume su propio widget web, parámetro
# `integration=<casa>`). Verificado en vivo el 2026-09-20 con el mismo partido
# en las tres (LaLiga, Valencia - Real Sociedad): mismos IDs de evento, mismos
# tipos de mercado (`typeId` global de Altenar), cientos de mercados por
# partido incluyendo córners y tarjetas pre-partido, que NO existen en ninguno
# de los dos comparadores (CuotasAhora/BetExplorer). Las tres tienen licencia
# DGOJ (Jokerbet: VERAMATIC ONLINE, S.A., comprobado en ordenacionjuego.es el
# 2026-09-20; Pastón: EUROAPUESTAS ONLINE, comprobado el 2026-09-16; Betway
# ya estaba en la lista verificada). El orden importa: la primera casa que
# lista un evento fija el nombre canónico del evento para las demás.
INTEGRATIONS: dict[str, str] = {
    "jokerbet": "jokerbet",
    "paston": "paston",
    "betway": "betway",
}

FOOTBALL_SPORT_ID = 66

# Ventana de partidos a escanear (horas desde ahora). Cada partido cuesta una
# petición de ~2 MB descomprimido por casa (~1,3 s), así que ampliarla
# multiplica el tiempo de un ciclo casi linealmente.
DEFAULT_HORIZON_HOURS = 48

# typeId de Altenar -> (prefijo de market_type, tipo de parseo). Solo se
# incluyen mercados con resultados excluyentes y exhaustivos (es lo que asume
# engine/arbitrage.py: margen = 1 - suma(1/cuota)). Quedan fuera a propósito:
# doble oportunidad, marcador exacto, escalas, combinadas y mercados de
# jugador, porque sus resultados se solapan o son demasiados. Los prefijos
# coinciden con los que ya usan CuotasAhora/BetExplorer cuando existe el mismo
# mercado ("1X2", "1X2_HT", "BTTS", "BTTS_HT", "OE", "DNB", "OU_<línea>",
# "AH_<línea>"); el resto son propios y solo cruzan entre casas Altenar.
_THREE_WAY = "three_way"
_FIRST_EVENT = "first_event"
_TWO_WAY_12 = "two_way_12"
_YES_NO = "yes_no"
_ODD_EVEN = "odd_even"
_TOTAL = "total"
_HANDICAP = "handicap"

FOOTBALL_MARKET_SPECS: dict[int, tuple[str, str]] = {
    # 1X2 y variantes
    1: ("1X2", _THREE_WAY),
    60: ("1X2_HT", _THREE_WAY),
    83: ("1X2_2H", _THREE_WAY),
    11: ("DNB", _TWO_WAY_12),
    136: ("CARDS_1X2", _THREE_WAY),
    162: ("CORNERS_1X2", _THREE_WAY),
    173: ("CORNERS_1X2_HT", _THREE_WAY),
    15741: ("SOT_1X2", _THREE_WAY),
    15742: ("SHOTS_1X2", _THREE_WAY),
    15743: ("OFFSIDES_1X2", _THREE_WAY),
    15744: ("FOULS_1X2", _THREE_WAY),
    # Primer/último evento (1 / Ninguno / 2)
    8: ("FIRST_GOAL", _FIRST_EVENT),
    9: ("LAST_GOAL", _FIRST_EVENT),
    62: ("FIRST_GOAL_HT", _FIRST_EVENT),
    84: ("FIRST_GOAL_2H", _FIRST_EVENT),
    163: ("CORNERS_FIRST", _FIRST_EVENT),
    164: ("CORNERS_LAST", _FIRST_EVENT),
    174: ("CORNERS_FIRST_HT", _FIRST_EVENT),
    175: ("CORNERS_LAST_HT", _FIRST_EVENT),
    31543: ("FIRST_FOUL", _FIRST_EVENT),
    31544: ("FIRST_OFFSIDE", _FIRST_EVENT),
    31546: ("FIRST_SHOT_ON_TARGET", _FIRST_EVENT),
    # Sí / No
    29: ("BTTS", _YES_NO),
    75: ("BTTS_HT", _YES_NO),
    95: ("BTTS_2H", _YES_NO),
    31: ("CS_HOME", _YES_NO),
    32: ("CS_AWAY", _YES_NO),
    76: ("CS_HOME_HT", _YES_NO),
    77: ("CS_AWAY_HT", _YES_NO),
    96: ("CS_HOME_2H", _YES_NO),
    97: ("CS_AWAY_2H", _YES_NO),
    33: ("WTN_HOME", _YES_NO),
    34: ("WTN_AWAY", _YES_NO),
    48: ("WIN_BOTH_HALVES_HOME", _YES_NO),
    49: ("WIN_BOTH_HALVES_AWAY", _YES_NO),
    50: ("WIN_ANY_HALF_HOME", _YES_NO),
    51: ("WIN_ANY_HALF_AWAY", _YES_NO),
    56: ("SCORE_BOTH_HALVES_HOME", _YES_NO),
    57: ("SCORE_BOTH_HALVES_AWAY", _YES_NO),
    17684: ("PENALTY", _YES_NO),
    # Impar / Par
    26: ("OE", _ODD_EVEN),
    27: ("OE_HOME", _ODD_EVEN),
    28: ("OE_AWAY", _ODD_EVEN),
    74: ("OE_HT", _ODD_EVEN),
    94: ("OE_2H", _ODD_EVEN),
    618: ("OE_HOME_HT", _ODD_EVEN),
    619: ("OE_AWAY_HT", _ODD_EVEN),
    172: ("CORNERS_OE", _ODD_EVEN),
    183: ("CORNERS_OE_HT", _ODD_EVEN),
    3286: ("CORNERS_OE_HOME", _ODD_EVEN),
    3287: ("CORNERS_OE_AWAY", _ODD_EVEN),
    3279: ("CARDS_OE", _ODD_EVEN),
    3288: ("CARDS_OE_HOME", _ODD_EVEN),
    3289: ("CARDS_OE_AWAY", _ODD_EVEN),
    # Más / Menos de (todas las líneas dentro de un mismo mercado)
    18: ("OU", _TOTAL),
    68: ("OU_HT", _TOTAL),
    90: ("OU_2H", _TOTAL),
    19: ("OU_HOME", _TOTAL),
    20: ("OU_AWAY", _TOTAL),
    69: ("OU_HOME_HT", _TOTAL),
    70: ("OU_AWAY_HT", _TOTAL),
    91: ("OU_HOME_2H", _TOTAL),
    92: ("OU_AWAY_2H", _TOTAL),
    166: ("CORNERS_OU", _TOTAL),
    167: ("CORNERS_OU_HOME", _TOTAL),
    168: ("CORNERS_OU_AWAY", _TOTAL),
    177: ("CORNERS_OU_HT", _TOTAL),
    178: ("CORNERS_OU_HOME_HT", _TOTAL),
    179: ("CORNERS_OU_AWAY_HT", _TOTAL),
    139: ("CARDS_OU", _TOTAL),
    140: ("CARDS_OU_HOME", _TOTAL),
    141: ("CARDS_OU_AWAY", _TOTAL),
    152: ("CARDS_OU_HT", _TOTAL),
    153: ("CARDS_OU_HOME_HT", _TOTAL),
    154: ("CARDS_OU_AWAY_HT", _TOTAL),
    15739: ("OFFSIDES_OU", _TOTAL),
    15730: ("OFFSIDES_OU_HOME", _TOTAL),
    15731: ("OFFSIDES_OU_AWAY", _TOTAL),
    15737: ("SOT_OU", _TOTAL),
    15726: ("SOT_OU_HOME", _TOTAL),
    15727: ("SOT_OU_AWAY", _TOTAL),
    15738: ("SHOTS_OU", _TOTAL),
    15728: ("SHOTS_OU_HOME", _TOTAL),
    15729: ("SHOTS_OU_AWAY", _TOTAL),
    15740: ("FOULS_OU", _TOTAL),
    15732: ("FOULS_OU_HOME", _TOTAL),
    15733: ("FOULS_OU_AWAY", _TOTAL),
    # Hándicap asiático (dos resultados, la línea se expresa desde el local)
    16: ("AH", _HANDICAP),
    66: ("AH_HT", _HANDICAP),
    88: ("AH_2H", _HANDICAP),
    165: ("CORNERS_AH", _HANDICAP),
    176: ("CORNERS_AH_HT", _HANDICAP),
}

# Resultados fijos de cada tipo de mercado. Los que hacen referencia a un
# equipo ("1"/"2") NO se reconocen por su texto: cada casa los nombra distinto
# (Betway "1"/"2", Jokerbet/Pastón el nombre del equipo, verificado en vivo el
# 2026-09-20) - se identifican por `competitorId` (ver _team_label). Aquí solo
# van los resultados sin equipo, con todas las variantes de texto vistas.
_NON_TEAM_LABELS = {
    _THREE_WAY: {"empate": "X", "x": "X", "draw": "X"},
    _FIRST_EVENT: {"ninguno": "None", "none": "None"},
    _TWO_WAY_12: {},
}
_TEAM_OUTCOME_KINDS = {_THREE_WAY, _FIRST_EVENT, _TWO_WAY_12}
_EXPECTED_OUTCOMES = {
    _THREE_WAY: {"1", "X", "2"},
    _FIRST_EVENT: {"1", "None", "2"},
    _TWO_WAY_12: {"1", "2"},
    _YES_NO: {"Yes", "No"},
    _ODD_EVEN: {"Odd", "Even"},
}
_YES_NO_LABELS = {"sí": "Yes", "si": "Yes", "yes": "Yes", "no": "No"}
_ODD_EVEN_LABELS = {"impar": "Odd", "par": "Even", "odd": "Odd", "even": "Even"}

_TOTAL_RE = re.compile(r"^(m[aá]s|menos) de (\d+(?:\.\d+)?)$", re.IGNORECASE)
_HANDICAP_RE = re.compile(r"^.+ \(([+-]?\d+(?:\.\d+)?)\)$")


def _display_price(price: float) -> float:
    """Altenar devuelve cuotas con hasta 4 decimales (p.ej. 2.7143) pero la
    web las muestra con 2 - es lo que ve y puede apostar el usuario. Se
    redondea half-up como `toFixed(2)` de JS.
    """
    return math.floor(price * 100 + 0.5) / 100


def _fmt(value: float, signed: bool = False) -> str:
    if value == int(value):
        text = str(int(value))
    else:
        text = f"{value:g}"
    if signed and value > 0:
        text = "+" + text
    return text


def _fmt_line(line: float, signed: bool = False) -> str:
    """Línea de mercado como string estable. Las líneas de cuarto (x.25/x.75)
    se expresan como "dos líneas" ("2/2.5", "-0.5/-1", la más cercana a cero
    primero), igual que las normaliza providers/betexplorer.py, para que
    ambos proveedores puedan cruzarse en la misma línea.
    """
    if (line * 4) % 2 == 1:
        first, second = sorted((line - 0.25, line + 0.25), key=abs)
        return f"{_fmt(first)}/{_fmt(second)}"
    return _fmt(line, signed=signed)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _flat_odd_ids(market: dict) -> set[int]:
    ids: set[int] = set()
    for key in ("desktopOddIds", "mobileOddIds", "oddIds"):
        for group in market.get(key) or []:
            if isinstance(group, list):
                ids.update(group)
            else:
                ids.add(group)
    return ids


def _pick_market_variants(markets: list[dict]) -> dict[int, dict]:
    """Un mismo mercado (mismo `id`) aparece dos veces: vista normal y vista
    "Crear apuesta" (`isBB`), esta última con menos líneas. Nos quedamos con
    la variante que trae más cuotas.
    """
    best: dict[int, dict] = {}
    for market in markets:
        market_id = market.get("id")
        current = best.get(market_id)
        if current is None or len(_flat_odd_ids(market)) > len(_flat_odd_ids(current)):
            best[market_id] = market
    return best


def _team_label(odd: dict, home_id, away_id) -> str | None:
    """"1" (local) / "2" (visitante) según el `competitorId` de la cuota, sin
    depender del texto (Betway "1"/"2", Jokerbet/Pastón el nombre del equipo).
    """
    competitor = odd.get("competitorId")
    if competitor is None:
        return None
    if competitor == home_id:
        return "1"
    if competitor == away_id:
        return "2"
    return None


def parse_event_markets(
    details: dict,
    event_name: str,
    sport: str,
    bookmaker: str,
    competitor_ids: tuple | None = None,
) -> list[Market]:
    """Convierte la respuesta de GetEventDetails de una casa en Markets.

    `competitor_ids` = (id del local, id del visitante); si no se pasa se
    toman de `details["competitors"]` (el primero es el local).
    """
    if competitor_ids is None:
        competitors = details.get("competitors", [])
        competitor_ids = tuple(c["id"] for c in competitors[:2]) if len(competitors) >= 2 else (None, None)
    home_id, away_id = competitor_ids
    odds_by_id = {odd["id"]: odd for odd in details.get("odds", [])}
    markets: list[Market] = []
    for market in _pick_market_variants(details.get("markets", [])).values():
        spec = FOOTBALL_MARKET_SPECS.get(market.get("typeId"))
        if spec is None:
            continue
        prefix, kind = spec
        available = []
        for odd_id in _flat_odd_ids(market):
            odd = odds_by_id.get(odd_id)
            # oddStatus 0 = disponible; el resto (suspendida, etc.) no se
            # puede apostar y no debe entrar en un cálculo de arbitraje.
            if odd is None or odd.get("oddStatus") != 0:
                continue
            price = _display_price(float(odd["price"]))
            if price <= 1.0:
                continue
            available.append((_clean_name(str(odd["name"])), price, _team_label(odd, home_id, away_id)))

        if kind in _EXPECTED_OUTCOMES:
            market_obj = _parse_fixed_outcomes(event_name, sport, bookmaker, prefix, kind, available)
            if market_obj is not None:
                markets.append(market_obj)
        elif kind == _TOTAL:
            markets.extend(_parse_totals(event_name, sport, bookmaker, prefix, available))
        elif kind == _HANDICAP:
            markets.extend(_parse_handicaps(event_name, sport, bookmaker, prefix, available))
    return markets


def _label_for(kind: str, name: str, team: str | None) -> str | None:
    lowered = name.lower()
    if kind in _TEAM_OUTCOME_KINDS and team is not None:
        return team
    if kind in _NON_TEAM_LABELS:
        return _NON_TEAM_LABELS[kind].get(lowered)
    if kind == _YES_NO:
        # Pastón: "Ambos Marcan: Si" / "Ambos Marcan: No"
        return _YES_NO_LABELS.get(lowered.split(":")[-1].strip())
    if kind == _ODD_EVEN:
        return _ODD_EVEN_LABELS.get(lowered)
    return None


def _parse_fixed_outcomes(event, sport, bookmaker, prefix, kind, available) -> Market | None:
    outcomes = []
    for name, price, team in available:
        label = _label_for(kind, name, team)
        if label is None:
            # Un resultado no reconocido significa que el mercado no es el
            # que esperamos: mejor descartarlo entero que emitir un conjunto
            # incompleto que fabricaría un arbitraje falso.
            return None
        outcomes.append(Outcome(name=label, bookmaker=bookmaker, odds=price))
    expected = _EXPECTED_OUTCOMES[kind]
    if {o.name for o in outcomes} != expected or len(outcomes) != len(expected):
        return None
    return Market(event=event, sport=sport, market_type=prefix, outcomes=outcomes)


def _parse_totals(event, sport, bookmaker, prefix, available) -> list[Market]:
    by_line: dict[float, dict[str, float]] = {}
    for name, price, _team in available:
        match = _TOTAL_RE.match(name)
        if match is None:
            continue
        side = "Under" if match.group(1).lower() == "menos" else "Over"
        by_line.setdefault(float(match.group(2)), {})[side] = price
    return [
        Market(
            event=event,
            sport=sport,
            market_type=f"{prefix}_{_fmt_line(line)}",
            outcomes=[
                Outcome(name="Over", bookmaker=bookmaker, odds=sides["Over"]),
                Outcome(name="Under", bookmaker=bookmaker, odds=sides["Under"]),
            ],
        )
        for line, sides in sorted(by_line.items())
        if "Over" in sides and "Under" in sides
    ]


def _parse_handicaps(event, sport, bookmaker, prefix, available) -> list[Market]:
    # Cada resultado trae su propia línea ("1 (+2.5)" / "Real Sociedad
    # (-2.5)"); el equipo se identifica por competitorId y ambos lados de una
    # misma línea se emparejan usando la línea del local.
    by_line: dict[float, dict[str, float]] = {}
    for name, price, team in available:
        match = _HANDICAP_RE.match(name)
        if match is None or team is None:
            continue
        value = float(match.group(1))
        home_line = value if team == "1" else -value
        by_line.setdefault(home_line, {})[team] = price
    return [
        Market(
            event=event,
            sport=sport,
            market_type=f"{prefix}_{_fmt_line(line, signed=True)}",
            outcomes=[
                Outcome(name="1", bookmaker=bookmaker, odds=sides["1"]),
                Outcome(name="2", bookmaker=bookmaker, odds=sides["2"]),
            ],
        )
        for line, sides in sorted(by_line.items())
        if "1" in sides and "2" in sides
    ]


class AltenarProvider(OddsProvider):
    """Casas de apuestas españolas sobre la plataforma Altenar (Jokerbet,
    Pastón, Betway), leídas por la API JSON pública de su propio widget, sin
    navegador (a diferencia del resto de proveedores, que usan Playwright).

    Ventajas frente al scraping del DOM: el widget se pinta dentro de un
    Shadow DOM con clases CSS con hash (frágiles), mientras que la API tiene
    esquema estable y devuelve TODOS los mercados de un partido en una sola
    petición. Incluye córners, tarjetas, fueras de juego, tiros, faltas y
    mercados por mitad pre-partido - inexistentes en los comparadores.

    Solo se piden detalles de los partidos que listan al menos dos de las casas
    (un mercado de una sola casa no puede ser arbitraje entre casas de esta
    plataforma) y dentro de `horizon_hours`. El nombre del evento se fija una
    sola vez por partido (el de la primera casa que lo lista), porque cada casa
    nombra distinto a los equipos ("Valencia CF"/"Valencia", "Athletic
    Club"/"Athletic Bilbao") y así los mercados de las tres cruzan de forma
    exacta sin depender de la tabla de alias de equipos.

    OJO con las reglas de liquidación: córners y tarjetas los liquida cada
    casa con sus propias normas (p.ej. cómo puntúa una roja o si cuentan los
    córners anulados por el VAR). Al ser todas Altenar lo normal es que
    coincidan, pero conviene comprobarlo en las condiciones de cada casa
    antes de apostar dinero real a una surebet de estos mercados.
    """

    name = "altenar"
    fast_recheck = True

    def __init__(
        self,
        integrations: dict[str, str] | None = None,
        horizon_hours: int | None = None,
        max_workers: int = 4,
    ):
        self.integrations = integrations or INTEGRATIONS
        self.horizon_hours = horizon_hours or int(os.environ.get("ALTENAR_HORIZON_HOURS", DEFAULT_HORIZON_HOURS))
        self.max_workers = max_workers

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        with httpx.Client(timeout=30, headers={"Accept": "application/json"}) as client:
            return self._fetch_football(client)

    def _get_json(self, client, endpoint: str, integration: str, **params) -> dict:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = client.get(
                    API_BASE + endpoint,
                    params={**COMMON_PARAMS, "integration": integration, **params},
                )
                response.raise_for_status()
                return response.json()
            except httpx.TransportError as exc:
                # cortes puntuales de conexión: se reintenta con espera creciente
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Altenar: red inestable en {endpoint}/{integration}") from last_error

    def _list_events(self, client, integration: str) -> dict[int, dict]:
        data = self._get_json(
            client,
            "GetEvents",
            integration,
            eventCount=0,
            sportId=FOOTBALL_SPORT_ID,
            catIds=0,
            champIds=0,
            group="AllEvents",
            period="periodall",
            withLive="false",
            outrightsDisplay="none",
            marketTypeIds="",
            couponType=0,
            marketGroupId="",
            startDate="",
            endDate="",
        )
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)
        events = {}
        for event in data.get("events", []):
            # status 0 = pre-partido (no en juego); este sistema es solo
            # pre-partido a propósito.
            if event.get("status") != 0 or " vs. " not in event.get("name", ""):
                continue
            start = datetime.fromisoformat(event["startDate"].replace("Z", "+00:00"))
            if not (now < start <= limit):
                continue
            events[event["id"]] = event
        return events

    def _fetch_football(self, client) -> list[Market]:
        listings: dict[str, dict[int, dict]] = {}
        for integration in self.integrations:
            try:
                listings[integration] = self._list_events(client, integration)
            except Exception:
                logger.warning("Altenar: fallo listando eventos de %s", integration, exc_info=True)
                listings[integration] = {}

        seen_by: dict[int, int] = {}
        canonical: dict[int, str] = {}
        competitors: dict[int, tuple | None] = {}
        starts: dict[int, datetime] = {}
        for integration in self.integrations:
            for event_id, event in listings[integration].items():
                seen_by[event_id] = seen_by.get(event_id, 0) + 1
                canonical.setdefault(event_id, self._canonical_name(event["name"]))
                starts.setdefault(event_id, datetime.fromisoformat(event["startDate"].replace("Z", "+00:00")))
                # [local, visitante] - mismo orden que el nombre "Local vs. Visitante"
                ids = event.get("competitorIds") or []
                competitors.setdefault(event_id, tuple(ids[:2]) if len(ids) >= 2 else None)
        jobs = [
            (integration, event_id)
            for integration in self.integrations
            for event_id in listings[integration]
            if seen_by[event_id] >= 2
        ]
        logger.info("Altenar: %d eventos comparables, %d peticiones de detalle", len({j[1] for j in jobs}), len(jobs))

        def fetch(job):
            integration, event_id = job
            try:
                details = self._get_json(
                    client, "GetEventDetails", integration, eventId=event_id, showNonBoosts="false"
                )
            except Exception:
                logger.warning("Altenar: fallo en detalle %s/%s", integration, event_id, exc_info=True)
                return []
            parsed = parse_event_markets(
                details, canonical[event_id], "futbol", self.integrations[integration], competitors[event_id]
            )
            for market in parsed:
                market.start_time = starts[event_id]
            return parsed

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for result in pool.map(fetch, jobs):
                markets.extend(result)
        return markets

    @staticmethod
    def _canonical_name(raw: str) -> str:
        home, away = raw.split(" vs. ", 1)
        return f"{_clean_name(home)} vs. {_clean_name(away)}"
