"""Un ciclo de escaneo (fetch -> cruce de eventos -> detección -> dedupe -> aviso),
extraído de main.py para poder reutilizarlo tanto desde el proceso de larga duración
(VM + systemd, con el estado en memoria) como desde un script de un solo disparo
(GitHub Actions, con el estado cargado/guardado en un JSON entre ejecuciones).
"""

import asyncio
from collections.abc import Awaitable, Callable

from providers.base import OddsProvider
from storage.db import save_comparisons, save_opportunity

from .arbitrage import compare_market, format_stakes
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
            # fetch_markets es síncrono y hace asyncio.run() por dentro (cada
            # provider lanza su propio Playwright); como run_scan_cycle ya
            # corre dentro de un event loop (main.py o scan_once_action.py),
            # llamarlo directamente aquí chocaría con ese loop en marcha
            # ("asyncio.run() cannot be called from a running event loop").
            # Se ejecuta en un hilo aparte para darle un loop propio.
            raw_markets.extend(await asyncio.to_thread(provider.fetch_markets, sports))
        except Exception:
            logger.exception("Fallo obteniendo datos de %s", provider.name)

    seen_keys: set[str] = set()
    comparisons = []

    for grouped in group_by_event(raw_markets):
        market = best_odds_per_outcome(grouped)
        comparison = compare_market(market, bankroll, min_margin)
        comparisons.append(comparison)

        if not comparison.is_surebet:
            continue

        key = opportunity_key(comparison)
        seen_keys.add(key)
        previous_margin = active_state.get(key)
        is_new_or_changed = (
            previous_margin is None
            or abs(comparison.margin - previous_margin) >= MARGIN_CHANGE_THRESHOLD
        )
        active_state[key] = comparison.margin

        if not is_new_or_changed:
            continue

        row_id = save_opportunity(db_path, comparison)
        logger.info(
            "Surebet detectada (#%s): %s margen %.2f%%", row_id, market.event, comparison.margin * 100
        )
        await notify(
            f"🚨 Nueva surebet\n🎯 {market.event} ({market.sport}, {market.market_type})\n"
            f"Margen: {comparison.margin * 100:.2f}% | Beneficio: {comparison.guaranteed_profit}€\n"
            f"{format_stakes(comparison.stakes)}",
        )

    # Registra el estado de *todas* las comparaciones (sean o no surebet)
    # para el panel web, aparte del dedupe de arriba que solo mira surebets.
    save_comparisons(db_path, comparisons)

    # Las que ya no aparecen en este scan se consideran cerradas: si vuelven a
    # aparecer más adelante, se tratan como nuevas y se vuelve a avisar.
    for key in list(active_state):
        if key not in seen_keys:
            del active_state[key]
