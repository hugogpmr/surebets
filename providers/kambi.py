import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from engine.models import Market, Outcome
from providers.altenar import DEFAULT_HORIZON_HOURS, _fmt_line
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

API_BASE = "https://eu-offering-api.kambicdn.com/offering/v2018/"
COMMON_PARAMS = {
    "lang": "es_ES",
    "market": "ES",
    "client_id": "2",
    "channel_id": "1",
    "ncid": "1",
    "useCombined": "true",
}

# Casas españolas sobre la plataforma Kambi (segunda plataforma B2B, distinta
# de Altenar), leídas por su API pública de ofertas sin autenticación - la
# misma que consume el propio front de cada casa. Clave = código de operador de
# Kambi, valor = nombre de casa que usa el resto del sistema. Verificado en
# vivo el 2026-09-20 con el mismo partido (Valencia - Real Sociedad): Paf
# ("pafes") y LeoVegas ("leoes") devuelven ~458 ofertas/102 criterios pre-
# partido cada una, con córners, tarjetas, faltas y mercados por mitad.
# Licencias DGOJ: Paf ya verificada (2026-09-16); LeoVegas comprobada en
# ordenacionjuego.es el 2026-09-20 (LEOESP, S.A. / Leovegas Gaming PLC, apuestas
# deportivas, opera leovegas.es).
# Speedybet (mismo grupo que Paf, la web dice que usa Kambi) queda sin
# resolver: no se encontró su código de operador (probados varios nombres).
OPERATORS: dict[str, str] = {
    "pafes": "paf",
    "leoes": "leovegas",
    # Añadidas el 2026-09-21; los códigos salen del tráfico real de cada web
    # (Speedybet: settings-api.kambicdn.com/pafspeedybetes__startup.json) o de
    # probar el nombre en la API pública. Licencias en el registro de la DGOJ:
    # Yosports = RANK DIGITAL CEUTA, S.A.; Botemanía = GAMESYS SPAIN, S.A.;
    # Speedybet = PAF GAMES, S.A. (mismo grupo que Paf: mismo equipo de traders,
    # así que sus precios serán casi idénticos a los de Paf).
    "yosportses": "yosports",
    "botemaniaes": "botemania",
    "pafspeedybetes": "speedybet",
}

# Slug de deporte en la URL de listView (verificado en vivo 2026-09-24: ambos
# devuelven cientos de eventos pre-partido). Antes estas claves ("baloncesto_*"/
# "tenis_*" en main.py/scripts/scan_once_action.py) solo las cubría CuotasAhora.
SPORT_PATHS: dict[str, str] = {"futbol": "football", "baloncesto": "basketball", "tenis": "tennis"}

# Kambi devuelve cuotas y líneas en milésimas (1910 = 1.91, 2500 = 2.5).
_MILLI = 1000

_PERIOD_RE = re.compile(
    r"^(?P<base>.*?)(?: - (?P<period>1st Half|2nd Half|Quarter [1-4]|Including Overtime|Set 1|Set 2))?$"
)
# "won by" es el formato de tenis ("Total games won by Dane Sweeny"); "by"/"By"/"-"
# el de fútbol/baloncesto ("Total Points by <equipo>"). Insensible a mayúsculas: el
# nombre de la métrica llega en minúscula en el primer caso ("games") y en
# mayúscula en el segundo ("Points").
_TEAM_TOTAL_RE = re.compile(r"^Total (?P<metric>Goals|Corners|Cards|Points|Games)(?: won by| by| By| -) (?P<team>.+)$", re.IGNORECASE)

_METRIC_PREFIX = {"Goals": "OU", "Corners": "CORNERS_OU", "Cards": "CARDS_OU", "Points": "OU", "Games": "OU"}
_TOTAL_BASES = {
    "Total Goals": "OU",
    "Total Corners": "CORNERS_OU",
    "Total Cards": "CARDS_OU",
    "Total Points": "OU",  # baloncesto (incl. prórroga salvo sufijo de mitad/cuarto)
    "Total Games": "OU",  # tenis: total de juegos del partido (o de un set, con sufijo)
    "Total Sets": "SETS_OU",  # tenis: total de sets jugados
}
_MOST_BASES = {"Most Corners": "CORNERS_1X2", "Most Cards": "CARDS_1X2"}

_THREE_WAY = {"OT_ONE": "1", "OT_CROSS": "X", "OT_TWO": "2"}
_TWO_WAY_12 = {"OT_ONE": "1", "OT_TWO": "2"}
_YES_NO = {"OT_YES": "Yes", "OT_NO": "No"}
_ODD_EVEN = {"OT_ODD": "Odd", "OT_EVEN": "Even"}
# Doble oportunidad (verificado en vivo el 2026-09-21): local o empate / local o visitante /
# empate o visitante.
_DOUBLE_CHANCE = {"OT_ONE_OR_CROSS": "1X", "OT_ONE_OR_TWO": "12", "OT_CROSS_OR_TWO": "X2"}

# Sufijos de periodo reconocidos en el `criterion.englishLabel` ("Handicap -
# 1st Half", "Total Points - Quarter 1"...). Añadidos 2026-09-24 para
# baloncesto ("Quarter 1".."Quarter 4", "Including Overtime" = partido
# completo, mismo prefijo que sin sufijo) y tenis ("Set 1"/"Set 2" en mercados
# de líneas, p.ej. "Total Games - Set 1"; el ganador del set es una label
# aparte, "Set 1"/"Set 2" sin prefijo, ver más abajo).
_PERIOD_SUFFIXES = {
    "1st Half": "_HT",
    "2nd Half": "_2H",
    "Quarter 1": "_Q1",
    "Quarter 2": "_Q2",
    "Quarter 3": "_Q3",
    "Quarter 4": "_Q4",
    "Including Overtime": "",
    "Set 1": "_SET1",
    "Set 2": "_SET2",
}


def _period_suffix(period: str | None) -> str:
    return _PERIOD_SUFFIXES.get(period, "")


def _price(milli) -> float | None:
    """Cuota decimal a 2 decimales (half-up), o None si no hay cuota."""
    if milli is None:
        return None
    value = math.floor(milli / _MILLI * 100 + 0.5) / 100
    return value if value > 1.0 else None


def _outcome(name: str, bookmaker: str, offer: dict, raw: dict) -> Outcome:
    """Selección con los metadatos que Kambi sí expone: cash out (la oferta y la
    selección deben tenerlo activo; se ha visto ENABLED en la oferta y DISABLED
    en alguna de sus selecciones) y la hora del último cambio de cuota."""
    changed = raw.get("changedDate")
    try:
        odds_changed_at = datetime.fromisoformat(changed.replace("Z", "+00:00")) if changed else None
    except ValueError:
        odds_changed_at = None
    statuses = (offer.get("cashOutStatus"), raw.get("cashOutStatus"))
    return Outcome(
        name=name,
        bookmaker=bookmaker,
        odds=_price(raw["odds"]),
        cash_out=all(s == "ENABLED" for s in statuses) if any(statuses) else None,
        odds_changed_at=odds_changed_at,
    )


def _open_outcomes(offer: dict) -> list[dict] | None:
    """Todos los resultados de la oferta o None si alguno no está abierto:
    una oferta con un resultado suspendido no es un mercado completo y no
    puede entrar en un cálculo de arbitraje.
    """
    outcomes = offer.get("outcomes", [])
    if not outcomes or any(o.get("status") != "OPEN" or _price(o.get("odds")) is None for o in outcomes):
        return None
    return outcomes


def _fixed_market(event, sport, bookmaker, prefix, offer, mapping) -> Market | None:
    outcomes = _open_outcomes(offer)
    if outcomes is None:
        return None
    labels = [mapping.get(o.get("type")) for o in outcomes]
    if None in labels or set(labels) != set(mapping.values()) or len(labels) != len(mapping):
        return None
    return Market(
        event=event,
        sport=sport,
        market_type=prefix,
        outcomes=[_outcome(label, bookmaker, offer, o) for label, o in zip(labels, outcomes)],
    )


def _total_market(event, sport, bookmaker, prefix, offer) -> Market | None:
    outcomes = _open_outcomes(offer)
    if outcomes is None or len(outcomes) != 2:
        return None
    by_type = {o.get("type"): o for o in outcomes}
    if set(by_type) != {"OT_OVER", "OT_UNDER"} or by_type["OT_OVER"].get("line") != by_type["OT_UNDER"].get("line"):
        return None
    line = by_type["OT_OVER"].get("line")
    if line is None:
        return None
    return Market(
        event=event,
        sport=sport,
        market_type=f"{prefix}_{_fmt_line(line / _MILLI)}",
        outcomes=[
            _outcome("Over", bookmaker, offer, by_type["OT_OVER"]),
            _outcome("Under", bookmaker, offer, by_type["OT_UNDER"]),
        ],
    )


def _handicap_market(event, sport, bookmaker, prefix, offer, home, away) -> Market | None:
    outcomes = _open_outcomes(offer)
    if outcomes is None or len(outcomes) != 2:
        return None
    sides: dict[str, tuple[float, Outcome]] = {}
    for outcome in outcomes:
        line = outcome.get("line")
        if line is None:
            return None
        participant = outcome.get("participant")
        if participant == home:
            sides["1"] = (line / _MILLI, _outcome("1", bookmaker, offer, outcome))
        elif participant == away:
            sides["2"] = (-line / _MILLI, _outcome("2", bookmaker, offer, outcome))
    # Ambos lados deben describir la misma línea expresada desde el local.
    if set(sides) != {"1", "2"} or sides["1"][0] != sides["2"][0]:
        return None
    return Market(
        event=event,
        sport=sport,
        market_type=f"{prefix}_{_fmt_line(sides['1'][0], signed=True)}",
        outcomes=[sides["1"][1], sides["2"][1]],
    )


def parse_event_offers(details: dict, event_name: str, sport: str, bookmaker: str, home: str, away: str) -> list[Market]:
    """Convierte la respuesta de betoffer/event/<id> de una casa en Markets.

    Los mercados se reconocen por `criterion.englishLabel` (independiente del
    idioma) y `betOfferType`. Solo se emiten resultados excluyentes y
    exhaustivos, con los mismos prefijos de market_type que providers/altenar.py
    y los comparadores, para que crucen entre plataformas.
    """
    markets: list[Market] = []
    asian_totals: list[Market] = []
    for offer in details.get("betOffers", []):
        label = offer.get("criterion", {}).get("englishLabel", "")
        offer_type = offer.get("betOfferType", {}).get("englishName", "")
        period = _PERIOD_RE.match(label)
        base, period_name = period.group("base").strip(), period.group("period")
        suffix = _period_suffix(period_name)

        market = None
        if offer_type == "Match":
            if base == "Full Time":
                market = _fixed_market(event_name, sport, bookmaker, "1X2", offer, _THREE_WAY)
            elif label == "Half Time":
                market = _fixed_market(event_name, sport, bookmaker, "1X2_HT", offer, _THREE_WAY)
            elif label == "2nd Half":
                market = _fixed_market(event_name, sport, bookmaker, "1X2_2H", offer, _THREE_WAY)
            elif base == "Draw No Bet":
                market = _fixed_market(event_name, sport, bookmaker, f"DNB{suffix}", offer, _TWO_WAY_12)
            elif base in _MOST_BASES:
                market = _fixed_market(event_name, sport, bookmaker, f"{_MOST_BASES[base]}{suffix}", offer, _THREE_WAY)
            # Baloncesto ("Moneyline - Including Overtime") y tenis ("Match Odds"):
            # ganador a dos bandas, sin empate posible.
            elif base in ("Moneyline", "Match Odds"):
                market = _fixed_market(event_name, sport, bookmaker, f"ML{suffix}", offer, _TWO_WAY_12)
            # Tenis: ganador de un set concreto ("Set 1"/"Set 2" es la label entera,
            # no un sufijo de otro mercado - a diferencia de "Total Games - Set 1").
            elif label in ("Set 1", "Set 2"):
                market = _fixed_market(event_name, sport, bookmaker, f"ML_SET{label[-1]}", offer, _TWO_WAY_12)
        elif offer_type == "Double Chance":
            if base == "Double Chance":  # no "... and Both Teams To Score", etc.
                market = _fixed_market(event_name, sport, bookmaker, f"DC{suffix}", offer, _DOUBLE_CHANCE)
        elif offer_type == "Yes/No":
            if base == "Both Teams To Score":
                market = _fixed_market(event_name, sport, bookmaker, f"BTTS{suffix}", offer, _YES_NO)
            elif base == "Penalty Kick awarded":
                market = _fixed_market(event_name, sport, bookmaker, "PENALTY", offer, _YES_NO)
        elif offer_type == "Over/Under":
            prefix = _TOTAL_BASES.get(base)
            if prefix is None:
                team_match = _TEAM_TOTAL_RE.match(base)
                if team_match and team_match.group("team") in (home, away):
                    side = "HOME" if team_match.group("team") == home else "AWAY"
                    prefix = f"{_METRIC_PREFIX[team_match.group('metric').capitalize()]}_{side}"
            if prefix is not None:
                market = _total_market(event_name, sport, bookmaker, f"{prefix}{suffix}", offer)
        elif offer_type == "Asian Over/Under" and base == "Asian Total":
            candidate = _total_market(event_name, sport, bookmaker, f"OU{suffix}", offer)
            if candidate is not None:
                asian_totals.append(candidate)
        elif offer_type == "Asian Handicap" and base == "Asian Handicap":
            market = _handicap_market(event_name, sport, bookmaker, f"AH{suffix}", offer, home, away)
        # Baloncesto: "Point Spread"/"Handicap" (puntos, incl. sufijo de mitad/cuarto).
        # Tenis: "Game Handicap" (juegos) y "Set Handicap" (sets ganados).
        elif offer_type == "Handicap":
            if base in ("Point Spread", "Handicap", "Game Handicap"):
                market = _handicap_market(event_name, sport, bookmaker, f"AH{suffix}", offer, home, away)
            elif base == "Set Handicap":
                market = _handicap_market(event_name, sport, bookmaker, f"SETS_AH{suffix}", offer, home, away)
        elif offer_type == "Odd/Even" and base == "Total Points Odd/Even":
            market = _fixed_market(event_name, sport, bookmaker, f"OE{suffix}", offer, _ODD_EVEN)

        if market is not None:
            markets.append(market)

    # "Total asiático" repite las líneas enteras/medias del "Total" normal; se
    # aprovecha solo para las que este último no ofrece (líneas de cuarto).
    have = {m.market_type for m in markets}
    markets.extend(m for m in asian_totals if m.market_type not in have)
    return markets


class KambiProvider(OddsProvider):
    """Casas españolas sobre la plataforma Kambi (Paf, LeoVegas), por su API
    pública de ofertas, sin navegador. Complemento de providers/altenar.py:
    otra plataforma y otro equipo de traders, así que los precios de córners,
    tarjetas y hándicaps difieren de los de Altenar - justo lo que hace
    posible un arbitraje ENTRE plataformas (dentro de una misma plataforma las
    casas comparten feed y los precios son casi idénticos).

    Fuente directa de la casa (no comparador), por lo que es la referencia más
    fiable de precio actual: verificado el 2026-09-20 que en la hora previa a un
    partido los comparadores pueden diferir de estas APIs hasta ~7% en el 1X2.

    Igual que Altenar: solo partidos pre-partido (`state == NOT_STARTED`)
    listados por al menos dos casas y dentro de `horizon_hours`, y el nombre del
    evento se fija una vez por partido. Kambi limita las peticiones (HTTP 429):
    se reintenta con espera creciente y se usan pocos hilos.

    Los IDs de evento de Kambi no coinciden con los de Altenar, así que el cruce
    entre plataformas depende de `engine/matching.py` (alias de equipos +
    similitud de texto): seguro en LaLiga (alias curados), y para el resto un
    partido cuyos nombres difieran demasiado entre plataformas simplemente no
    cruza (fallo seguro, se pierde la oportunidad pero no se inventa una).
    """

    name = "kambi"
    fast_recheck = True

    def __init__(
        self,
        operators: dict[str, str] | None = None,
        horizon_hours: int | None = None,
        max_workers: int = 2,
        exclude_esports: bool | None = None,
        exclude_women: bool | None = None,
    ):
        self.exclude_esports = exclude_esports_default() if exclude_esports is None else exclude_esports
        self.exclude_women = exclude_womens_default() if exclude_women is None else exclude_women
        self.operators = operators or OPERATORS
        self.horizon_hours = horizon_hours or int(os.environ.get("KAMBI_HORIZON_HOURS", DEFAULT_HORIZON_HOURS))
        self.max_workers = max_workers

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        requested = {key.split("_", 1)[0] for key in sports} & set(SPORT_PATHS)
        if not requested:
            return []
        with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
            markets: list[Market] = []
            for sport in requested:
                markets.extend(self._fetch_sport(client, sport))
            return markets

    def _get_json(self, client, operator: str, path: str, **params) -> dict:
        url = f"{API_BASE}{operator}/{path}"
        for attempt in range(4):
            try:
                response = client.get(url, params={**COMMON_PARAMS, **params})
            except httpx.TransportError:
                # cortes puntuales de conexión (SSL EOF, servidor que cuelga)
                # vistos en vivo con varias peticiones en paralelo
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"Kambi: límite de peticiones o red inestable persistente en {operator}/{path}")

    def _list_events(self, client, operator: str, sport: str = "futbol") -> dict[int, dict]:
        data = self._get_json(client, operator, f"listView/{SPORT_PATHS[sport]}/all/all/all/matches.json")
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)
        events = {}
        for item in data.get("events", []):
            event = item.get("event", {})
            if event.get("state") != "NOT_STARTED" or not event.get("homeName") or not event.get("awayName"):
                continue
            # La ruta del evento ("|Esports Football|" > "Cyber Live Arena", "Liga
            # MX Femenil (W)"...) y los nombres de equipo distinguen el fútbol
            # virtual y el femenino, que no queremos.
            labels = [event.get("group"), event["homeName"], event["awayName"]]
            for node in event.get("path") or []:
                labels += [node.get("name"), node.get("englishName")]
            if is_excluded(labels, self.exclude_esports, self.exclude_women, sport):
                continue
            start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
            if now < start <= limit:
                events[event["id"]] = event
        return events

    def _fetch_football(self, client) -> list[Market]:
        return self._fetch_sport(client, "futbol")

    def _fetch_sport(self, client, sport: str) -> list[Market]:
        listings: dict[str, dict[int, dict]] = {}
        for operator in self.operators:
            try:
                listings[operator] = self._list_events(client, operator, sport)
            except Exception:
                logger.warning("Kambi: fallo listando eventos de %s", operator, exc_info=True)
                listings[operator] = {}

        seen_by: dict[int, int] = {}
        reference: dict[int, dict] = {}
        for operator in self.operators:
            for event_id, event in listings[operator].items():
                seen_by[event_id] = seen_by.get(event_id, 0) + 1
                reference.setdefault(event_id, event)
        jobs = [
            (operator, event_id)
            for operator in self.operators
            for event_id in listings[operator]
            if seen_by[event_id] >= 2
        ]
        logger.info("Kambi: %d eventos comparables, %d peticiones de detalle", len({j[1] for j in jobs}), len(jobs))

        def fetch(job):
            operator, event_id = job
            event = reference[event_id]
            try:
                details = self._get_json(
                    client, operator, f"betoffer/event/{event_id}.json", includeParticipants="true"
                )
            except Exception:
                logger.warning("Kambi: fallo en detalle %s/%s", operator, event_id, exc_info=True)
                return []
            name = f"{event['homeName'].strip()} vs. {event['awayName'].strip()}"
            parsed = parse_event_offers(
                details, name, sport, self.operators[operator], event["homeName"], event["awayName"]
            )
            start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
            for market in parsed:
                market.start_time = start
            return parsed

        markets: list[Market] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for result in pool.map(fetch, jobs):
                markets.extend(result)
        return markets
