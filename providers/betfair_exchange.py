"""Betfair Exchange API oficial (API-NG), aparte del scraper DOM de la web de
apuestas fijas (`providers/betfair.py`) que ya usa este proyecto.

Hallazgo 2026-09-23 (`estudio_tecnicas_otros_bots.md`, sección 2): Betfair
ofrece una **Delayed Application Key gratuita** (REST/JSON-RPC, sin coste de
activación; solo el "Live App Key" para apostar de verdad cuesta una activación
de pago) con un delay de 1-180s — de sobra para arbitraje pre-partido, que es
el foco de este proyecto. Es un canal 100% oficial y soportado, cero riesgo de
bloqueo, a diferencia del scraper DOM actual (sensible a cambios de HTML y a
geo-IP en runners cloud, ver memoria del proyecto).

**IMPORTANTE - sin verificar en vivo**: a diferencia de todos los demás
providers de este repo (que solo se dan por buenos tras probarlos contra la
web/API real), este se ha escrito siguiendo la documentación oficial de
Betfair API-NG pero **no se ha podido ejecutar contra la API real** porque
hace falta una cuenta de Betfair + una app key que solo el usuario puede
generar (developer.betfair.com) - no es algo que se pueda crear en su nombre.
Antes de fiarte de sus resultados, corre `fetch_markets(["futbol"])` una vez
con tus credenciales en `.env` y revisa los mercados que devuelve.

Autenticación: login "interactivo" (usuario+contraseña+app key), NO el login
"no interactivo" por certificado (`identitysso-cert`) que Betfair recomienda
para bots de verdad - ese necesita generar un certificado TLS y subir la clave
pública a tu cuenta de Betfair, más fricción de la que compensa para un
escaneo de baja frecuencia como este. Si el login interactivo empieza a fallar
por límite de sesiones concurrentes, esa sería la alternativa a evaluar.

Flujo:
1. POST a `IDENTITY_LOGIN_URL` (usuario/contraseña + app key) -> sessionToken.
2. JSON-RPC a `BETTING_API_URL` (`listCompetitions` para encontrar el id de
   LaLiga, `listMarketCatalogue` para los mercados MATCH_ODDS del fútbol
   español, `listMarketBook` para los precios de cada uno).
3. El mercado "The Draw" identifica el empate; el resto se casan con el
   nombre del evento (`"Equipo A v Equipo B"`) para saber cuál es 1 y cuál 2.

La cuota que se guarda como `Outcome.odds` ya lleva descontada la comisión de
Betfair (`config.BETFAIR_EXCHANGE_COMMISSION`, ver ahí) sobre la ganancia neta:
el precio "a favor" que se ve en pantalla no es lo que de verdad se cobra, y
compararlo sin descontar la comisión infla el margen calculado.
"""

import logging

import httpx

import config
from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

IDENTITY_LOGIN_URL = "https://identitysso.betfair.com/api/login"
BETTING_API_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
SOCCER_EVENT_TYPE_ID = "1"
MATCH_ODDS = "MATCH_ODDS"
DRAW_RUNNER_NAME = "The Draw"
BOOKMAKER = "betfair_exchange"

# Texto de búsqueda de competición pasado a listCompetitions: el nombre exacto
# que usa Betfair para LaLiga en su propio catálogo (no confirmado en vivo,
# ver docstring del módulo).
COMPETITION_QUERY = "La Liga"


def _net_odds(back_price: float, commission: float) -> float:
    """Precio "a favor" (back) neto de comisión, como cuota decimal equivalente
    a la de una casa normal: la comisión solo se cobra sobre la ganancia neta
    (back_price - 1), no sobre el importe apostado."""
    return 1 + (back_price - 1) * (1 - commission)


class BetfairExchangeProvider(OddsProvider):
    """Ver docstring del módulo. Sin `config.BETFAIR_APP_KEY`/`BETFAIR_USERNAME`/
    `BETFAIR_PASSWORD` en `.env`, `fetch_markets` no hace nada (no rompe el
    escaneo): es opcional, a diferencia del resto de fuentes directas."""

    name = BOOKMAKER
    fast_recheck = True

    def __init__(
        self,
        app_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        commission: float | None = None,
        competition_query: str = COMPETITION_QUERY,
    ):
        self.app_key = app_key if app_key is not None else config.BETFAIR_APP_KEY
        self.username = username if username is not None else config.BETFAIR_USERNAME
        self.password = password if password is not None else config.BETFAIR_PASSWORD
        self.commission = commission if commission is not None else config.BETFAIR_EXCHANGE_COMMISSION
        self.competition_query = competition_query

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        if not (self.app_key and self.username and self.password):
            logger.debug("Betfair Exchange: sin credenciales en .env, se salta.")
            return []
        try:
            with httpx.Client(timeout=30) as client:
                session_token = self._login(client)
                return self._fetch_match_odds(client, session_token)
        except httpx.HTTPError:
            logger.warning("Betfair Exchange: fallo de red/HTTP", exc_info=True)
            return []
        except BetfairApiError as exc:
            logger.warning("Betfair Exchange: %s", exc)
            return []

    def _login(self, client: httpx.Client) -> str:
        response = client.post(
            IDENTITY_LOGIN_URL,
            headers={
                "X-Application": self.app_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("loginStatus") != "SUCCESS" or not data.get("sessionToken"):
            raise BetfairApiError(f"login fallido: {data.get('loginStatus')}")
        return data["sessionToken"]

    def _rpc(self, client: httpx.Client, session_token: str, method: str, params: dict) -> object:
        response = client.post(
            BETTING_API_URL,
            headers={
                "X-Application": self.app_key,
                "X-Authentication": session_token,
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "method": f"SportsAPING/v1.0/{method}", "params": params, "id": 1},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise BetfairApiError(f"{method}: {payload['error']}")
        return payload["result"]

    def _find_competition_id(self, client: httpx.Client, session_token: str) -> str | None:
        result = self._rpc(
            client,
            session_token,
            "listCompetitions",
            {"filter": {"eventTypeIds": [SOCCER_EVENT_TYPE_ID], "textQuery": self.competition_query}},
        )
        if not result:
            return None
        return result[0]["competition"]["id"]

    def _fetch_match_odds(self, client: httpx.Client, session_token: str) -> list[Market]:
        competition_id = self._find_competition_id(client, session_token)
        if competition_id is None:
            logger.warning("Betfair Exchange: no se encontró la competición '%s'", self.competition_query)
            return []

        catalogue = self._rpc(
            client,
            session_token,
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "competitionIds": [competition_id],
                    "marketTypeCodes": [MATCH_ODDS],
                },
                "maxResults": 100,
                "marketProjection": ["EVENT", "COMPETITION", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
            },
        )
        if not catalogue:
            return []

        market_ids = [m["marketId"] for m in catalogue]
        books = self._rpc(
            client,
            session_token,
            "listMarketBook",
            {"marketIds": market_ids, "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}},
        )
        books_by_id = {b["marketId"]: b for b in books}

        exclude_esports = exclude_esports_default()
        exclude_women = exclude_womens_default()
        markets: list[Market] = []
        for entry in catalogue:
            book = books_by_id.get(entry["marketId"])
            if book is None:
                continue
            parsed = _parse_match_odds(entry, book, self.commission)
            if parsed is None:
                continue
            competition_name = entry.get("competition", {}).get("name", "")
            teams = parsed.event.split(" vs. ")
            if is_excluded([competition_name, *teams], exclude_esports, exclude_women):
                continue
            markets.append(parsed)
        logger.info("Betfair Exchange: %d partidos 1X2 de '%s'", len(markets), self.competition_query)
        return markets


class BetfairApiError(Exception):
    pass


def _parse_match_odds(catalogue_entry: dict, book: dict, commission: float) -> Market | None:
    """`catalogue_entry` = un elemento de `listMarketCatalogue` (nombres de
    corredor y del evento); `book` = el `listMarketBook` correspondiente
    (precios). Se cruzan por `selectionId`, no por posición: el orden de los
    corredores no está garantizado igual entre ambas llamadas."""
    runners_meta = {r["selectionId"]: r["runnerName"] for r in catalogue_entry.get("runners", [])}
    prices = {r["selectionId"]: r for r in book.get("runners", [])}
    if len(runners_meta) != 3:
        return None

    draw_id = next((sid for sid, name in runners_meta.items() if name == DRAW_RUNNER_NAME), None)
    if draw_id is None:
        return None
    other_ids = [sid for sid in runners_meta if sid != draw_id]
    if len(other_ids) != 2:
        return None

    event_name = catalogue_entry.get("event", {}).get("name", "")
    home_name, _, away_name = event_name.partition(" v ")
    if not home_name or not away_name:
        return None

    def _match_side(team_name: str) -> int | None:
        return next((sid for sid in other_ids if runners_meta[sid].strip().lower() == team_name.strip().lower()), None)

    home_id, away_id = _match_side(home_name), _match_side(away_name)
    if home_id is None or away_id is None:
        # Los nombres de corredor no coinciden literalmente con el del evento:
        # se cae al orden que da Betfair (normalmente casa/fuera en ese orden).
        home_id, away_id = other_ids[0], other_ids[1]

    home_odds = _best_back(prices.get(home_id), commission)
    draw_odds = _best_back(prices.get(draw_id), commission)
    away_odds = _best_back(prices.get(away_id), commission)
    if home_odds is None or draw_odds is None or away_odds is None:
        return None

    outcomes = [
        Outcome(name="1", bookmaker=BOOKMAKER, odds=home_odds),
        Outcome(name="X", bookmaker=BOOKMAKER, odds=draw_odds),
        Outcome(name="2", bookmaker=BOOKMAKER, odds=away_odds),
    ]
    return Market(event=f"{home_name} vs. {away_name}", sport="futbol", market_type="1X2", outcomes=outcomes)


def _best_back(runner_book: dict | None, commission: float) -> float | None:
    if not runner_book or runner_book.get("status") != "ACTIVE":
        return None
    backs = runner_book.get("ex", {}).get("availableToBack", [])
    if not backs:
        return None
    price = backs[0].get("price")
    if not isinstance(price, (int, float)) or price <= 1.0:
        return None
    return _net_odds(price, commission)
