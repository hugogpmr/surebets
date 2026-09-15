"""Un ciclo de escaneo (fetch -> cruce de eventos -> detección -> dedupe -> aviso),
extraído de main.py para poder reutilizarlo tanto desde el proceso de larga duración
(VM + systemd, con el estado en memoria) como desde un script de un solo disparo
(GitHub Actions, con el estado cargado/guardado en un JSON entre ejecuciones).
"""

from collections.abc import Awaitable, Callable

from providers.base import OddsProvider
from storage.db import save_opportunity

from .arbitrage import evaluate_market
from .matching import best_odds_per_outcome, group_by_event

# Margen mínimo de cambio para considerar que una oportunidad ya notificada
# "cambió" y merece un nuevo aviso (en puntos porcentuales, no fracción).
MARGIN_CHANGE_THRESHOLD = 0.005

NotifyFn = Callable[[str], Awaitable[None]]


def opportunity_key(opp) -> str:
    bookmakers = ",".join(sorted({o.bookmaker for o in opp.market.outcomes}))
    return "||".join((opp.market.event, opp.market.sport, opp.market.market_type, bookmakers))


async def run_scan_cycle(
    providers: list[OddsProvider],
    sports: list[str],
    bankroll: float,
    min_margin: float,
    db_path: str,
    active_state: dict[str, float],
    notify: NotifyFn,
    logger,
) -> None:
    """Ejecuta un ciclo de escaneo. Muta `active_state` in-place (clave -> margen)
    para que el caller pueda persistirlo entre ejecuciones si hace falta.
    """
    raw_markets = []
    for provider in providers:
        try:
            raw_markets.extend(provider.fetch_markets(sports))
        except Exception:
            logger.exception("Fallo obteniendo datos de %s", provider.name)

    seen_keys: set[str] = set()

    for grouped in group_by_event(raw_markets):
        market = best_odds_per_outcome(grouped)
        opp = evaluate_market(market, bankroll, min_margin)
        if opp is None:
            continue

        key = opportunity_key(opp)
        seen_keys.add(key)
        previous_margin = active_state.get(key)
        is_new_or_changed = (
            previous_margin is None or abs(opp.margin - previous_margin) >= MARGIN_CHANGE_THRESHOLD
        )
        active_state[key] = opp.margin

        if not is_new_or_changed:
            continue

        row_id = save_opportunity(db_path, opp)
        logger.info("Surebet detectada (#%s): %s margen %.2f%%", row_id, market.event, opp.margin * 100)
        await notify(
            f"🚨 Nueva surebet\n🎯 {market.event} ({market.sport}, {market.market_type})\n"
            f"Margen: {opp.margin * 100:.2f}% | Beneficio: {opp.guaranteed_profit}€",
        )

    # Las que ya no aparecen en este scan se consideran cerradas: si vuelven a
    # aparecer más adelante, se tratan como nuevas y se vuelve a avisar.
    for key in list(active_state):
        if key not in seen_keys:
            del active_state[key]
