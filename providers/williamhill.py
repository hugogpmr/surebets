"""William Hill por su API JSON pública (plataforma OpenBet, prefijo `OB_` en
todos los IDs), sin navegador ni cookies.

`checklist.md`/README ya diagnosticaban bien la causa ("Bloqueo de IP
explícito... 'Data Centre block'"), pero solo se había probado desde IPs de
datacenter/VPN (este sandbox de desarrollo incluido: la propia web devuelve el
texto "desactiva tu VPN o evita utilizar un Centro de Datos"). Verificado en
vivo el 2026-09-23 desde el PC de producción del usuario (IP residencial):
`sports.williamhill.es` carga sin bloqueo, y detrás hay una API JSON pública
que responde igual (mismo JSON byte a byte) con o sin cookies de sesión, y
**también responde 200 desde este mismo sandbox** (a diferencia de la propia
página web, que sí sigue bloqueada aquí) — o sea, el bloqueo de IP es solo de
la web, no de esta API en concreto.

Endpoint: `GET /data/ngs/matches-competitions/matches/es-es/OB_SP9` (`OB_SP9`
= fútbol). Parámetros:
- `day`: `"today"` o el código de día de la semana tal cual los da
  `availableDays` de la propia respuesta (`"mon"`..`"sun"`, más `"future"` para
  todo lo que quede más allá de la semana);
- `page`: pagina por competición, no por partido (`hasMore`/`page` en la
  respuesta indican si hay que pedir la siguiente);
- `marketType`: el nombre TAL CUAL de un grupo de mercado, ver más abajo.

**Ojo con `marketType`**: pedir `"Ganador del partido"` (el texto que se ve en
la propia web) NO da el 1X2 normal, da la promo "2 Up" de William Hill
(`marketGroupNameToken: "|90 Minutes - 2 Up - Spain|"`, paga como ganador si tu
equipo se pone 2 goles arriba) — mismo caso que "Resultado VA (+2)" en
`providers/bwin.py`, no es una cuota de mercado normal y no sirve para
arbitraje. El 1X2 de verdad vive bajo el grupo
`"Ganador del Partido - Cuotas mejoradas"` (nombre de la web, algo confuso: por
dentro es simplemente `marketGroupNameToken: "|Ganador del partido|"`),
confirmado en vivo contrastando cuotas reales (Azerbaiyán-Tayikistán: 1.78 /
3.40 / 4.20 aquí, muy cerca de bet365 el mismo partido).

Solo 1X2 por ahora. Sin hora exacta de cierre de mercado ni corners/tarjetas
explorados (quedaría para otra sesión, cada mercado adicional es otro
`marketType` que probar en vivo).
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from engine.models import Market, Outcome
from providers.base import OddsProvider
from providers.filters import exclude_esports_default, exclude_womens_default, is_excluded

logger = logging.getLogger(__name__)

API_URL = "https://sports.williamhill.es/data/ngs/matches-competitions/matches/es-es/OB_SP9"
SOURCE_VERSION = "ngs@2.81.3"
# Nombre de grupo (tal cual lo pide la API en `marketType`) del 1X2 real, no de
# la promo "2 Up" (ver docstring del módulo).
MARKET_GROUP = "Ganador del Partido - Cuotas mejoradas"
BOOKMAKER = "williamhill"

DEFAULT_HORIZON_HOURS = 48

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
}


def _decimal_odds(selection: dict) -> float | None:
    if selection.get("status") != "A" or not selection.get("active") or not selection.get("displayed"):
        return None
    num, den = selection.get("currentPriceNum"), selection.get("currentPriceDen")
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)) or den <= 0:
        return None
    value = num / den + 1
    return value if value > 1.0 else None


def _parse_event(event: dict, competition_name: str) -> Market | None:
    if event.get("isInPlay") or event.get("settled") or event.get("status") != "A":
        return None
    start_raw = event.get("startDateTime")
    if not start_raw:
        return None
    start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))

    market = next(
        (m for m in event.get("markets", []) if m.get("name") == "Ganador del partido" and m.get("status") == "A"),
        None,
    )
    if market is None:
        return None
    selections = market.get("selections", [])
    if len(selections) != 3:
        return None
    draw = next((s for s in selections if s.get("name") == "Empate"), None)
    others = sorted((s for s in selections if s is not draw), key=lambda s: s.get("order", 0))
    if draw is None or len(others) != 2:
        return None
    home, away = others
    home_odds, draw_odds, away_odds = _decimal_odds(home), _decimal_odds(draw), _decimal_odds(away)
    if home_odds is None or draw_odds is None or away_odds is None:
        return None

    home_name, away_name = home.get("name"), away.get("name")
    if not home_name or not away_name:
        return None
    if is_excluded([competition_name, home_name, away_name], exclude_esports_default(), exclude_womens_default()):
        return None

    outcomes = [
        Outcome(name="1", bookmaker=BOOKMAKER, odds=home_odds),
        Outcome(name="X", bookmaker=BOOKMAKER, odds=draw_odds),
        Outcome(name="2", bookmaker=BOOKMAKER, odds=away_odds),
    ]
    return Market(
        event=f"{home_name} vs. {away_name}",
        sport="futbol",
        market_type="1X2",
        outcomes=outcomes,
        start_time=start,
    )


class WilliamHillProvider(OddsProvider):
    """William Hill por su API JSON pública (ver docstring del módulo). Solo
    1X2 de fútbol dentro de `horizon_hours`. API barata y sin navegador, así
    que se puede releer en el mismo escaneo para verificar surebets de margen
    muy alto."""

    name = BOOKMAKER
    fast_recheck = True

    def __init__(self, horizon_hours: int = DEFAULT_HORIZON_HOURS):
        self.horizon_hours = horizon_hours

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        if not any(key.split("_", 1)[0] == "futbol" for key in sports):
            return []
        with httpx.Client(headers=HEADERS, timeout=30) as client:
            return self._fetch_football(client)

    def _fetch_day(self, client: httpx.Client, day: str) -> tuple[list[dict], list[dict]]:
        """(competiciones, availableDays) de todas las páginas de ese día."""
        competitions: list[dict] = []
        available_days: list[dict] = []
        page = 0
        while True:
            params = {
                "source": SOURCE_VERSION,
                "sortKey": "competition",
                "day": day,
                "marketType": MARKET_GROUP,
                "availableDays": "true",
                "page": page,
            }
            response = client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()
            competitions.extend(data.get("competitions", []))
            if page == 0:
                available_days = data.get("availableDays", [])
            if not data.get("hasMore"):
                break
            page += 1
        return competitions, available_days

    def _fetch_football(self, client: httpx.Client) -> list[Market]:
        now = datetime.now(timezone.utc)
        limit = now + timedelta(hours=self.horizon_hours)

        try:
            competitions, available_days = self._fetch_day(client, "today")
        except httpx.HTTPError:
            logger.warning("William Hill: fallo leyendo 'today'", exc_info=True)
            return []

        for entry in available_days:
            try:
                day_date = datetime.fromisoformat(str(entry["date"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if day_date > limit or entry.get("day") not in (
                "mon", "tue", "wed", "thu", "fri", "sat", "sun",
            ):
                continue
            try:
                more, _ = self._fetch_day(client, entry["day"])
            except httpx.HTTPError:
                logger.warning("William Hill: fallo leyendo el día '%s'", entry.get("day"), exc_info=True)
                continue
            competitions.extend(more)

        markets: list[Market] = []
        seen_events: set[str] = set()
        for competition in competitions:
            competition_name = competition.get("name") or ""
            for event in competition.get("events", []):
                event_id = event.get("id")
                if not event_id or event_id in seen_events:
                    continue
                seen_events.add(event_id)
                parsed = _parse_event(event, competition_name)
                if parsed is None or parsed.start_time is None or not (now < parsed.start_time <= limit):
                    continue
                markets.append(parsed)
        logger.info("William Hill: %d partidos 1X2 pre-partido en las próximas %d h", len(markets), self.horizon_hours)
        return markets
