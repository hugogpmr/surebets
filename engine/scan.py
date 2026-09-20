"""Un ciclo de escaneo (fetch -> cruce de eventos -> detección -> control de
calidad -> confirmación -> aviso), extraído de main.py para poder reutilizarlo
tanto desde el proceso de larga duración (VM + systemd, con el estado en
memoria) como desde un script de un solo disparo (GitHub Actions / tarea
programada local, con el estado cargado/guardado en un JSON entre ejecuciones).
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from providers.base import OddsProvider
from storage.db import save_comparisons, save_opportunity

from .arbitrage import compare_market, format_stakes
from .matching import best_odds_per_outcome, group_by_event
from .quality import BLOCKING_FLAGS, FLAG_DESCRIPTIONS, MAX_MARGIN, WARN_MARGIN, assess

# Margen mínimo de cambio para considerar que una oportunidad ya notificada
# "cambió" y merece un nuevo aviso (en puntos porcentuales, no fracción).
MARGIN_CHANGE_THRESHOLD = 0.005

NotifyFn = Callable[[str], Awaitable[None]]


def opportunity_key(opp) -> str:
    bookmakers = ",".join(sorted({o.bookmaker for o in opp.market.outcomes}))
    return "||".join((opp.market.event, opp.market.sport, opp.market.market_type, bookmakers))


def normalize_state(raw: dict) -> dict[str, dict]:
    """Estado de oportunidades activas (clave -> {margin, cycles, notified}).
    Acepta el formato antiguo (clave -> margen suelto): esas ya se habían
    avisado en su día, así que entran como ya confirmadas y notificadas.
    """
    state: dict[str, dict] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            state[key] = {
                "margin": float(value.get("margin", 0.0)),
                "cycles": int(value.get("cycles", 1)),
                "notified": bool(value.get("notified", False)),
            }
        else:
            state[key] = {"margin": float(value), "cycles": 1, "notified": True}
    return state


def _kickoff_text(start_time: datetime | None) -> str | None:
    if start_time is None:
        return None
    try:
        from zoneinfo import ZoneInfo

        local = start_time.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception:  # sin base de datos de zonas horarias (Windows sin tzdata)
        local = start_time.astimezone(timezone.utc)
    delta = start_time - datetime.now(timezone.utc)
    hours = delta.total_seconds() / 3600
    when = f"en {hours:.1f} h" if hours >= 1 else f"en {max(int(delta.total_seconds() // 60), 0)} min"
    return f"{local:%d/%m %H:%M} ({when})"


def _source_by_leg(comparison) -> str:
    return ", ".join(
        f"{o.bookmaker}←{o.source}" for o in comparison.market.outcomes if o.source
    )


def format_alert(comparison) -> str:
    market = comparison.market
    stakes = comparison.rounded_stakes or comparison.stakes
    profit = comparison.rounded_profit if comparison.rounded_stakes else comparison.guaranteed_profit
    lines = [
        f"🚨 Nueva surebet (fiabilidad {comparison.reliability or 'n/d'})",
        f"🎯 {market.event} ({market.sport}, {market.market_type})",
    ]
    kickoff = _kickoff_text(market.start_time)
    if kickoff:
        lines.append(f"🕐 Empieza {kickoff}")
    lines.append(f"Margen: {comparison.margin * 100:.2f}% | Beneficio: {profit}€")
    lines.append(format_stakes(stakes))
    sources = _source_by_leg(comparison)
    if sources:
        lines.append(f"Fuentes: {sources}")
    for flag in comparison.flags:
        lines.append(f"⚠️ {FLAG_DESCRIPTIONS.get(flag, flag)}")
    return "\n".join(lines)


def _invalidate(comparison) -> None:
    """Una surebet con un flag bloqueante es un error de datos, no una
    oportunidad: deja de contar como surebet (sigue en el panel, con su flag)."""
    comparison.is_surebet = False
    comparison.stakes = None
    comparison.guaranteed_profit = None
    comparison.rounded_stakes = None
    comparison.rounded_profit = None


async def run_scan_cycle(
    providers: list[OddsProvider],
    sports: list[str],
    bankroll: float,
    min_margin: float,
    db_path: str,
    active_state: dict,
    notify: NotifyFn,
    logger,
    confirm_cycles: int = 1,
    round_step: float = 0.0,
    warn_margin: float = WARN_MARGIN,
    max_margin: float = MAX_MARGIN,
) -> None:
    """Ejecuta un ciclo de escaneo. Muta `active_state` in-place (clave ->
    {margin, cycles, notified}) para que el caller pueda persistirlo entre
    ejecuciones si hace falta.

    Una surebet solo se avisa (y se guarda en el histórico) cuando lleva
    `confirm_cycles` escaneos seguidos apareciendo: es lo que filtra las cuotas
    que parpadean un instante o que un comparador tenía ya desfasadas.
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
            fetched = await asyncio.to_thread(provider.fetch_markets, sports)
        except Exception:
            logger.exception("Fallo obteniendo datos de %s", provider.name)
            continue
        # Cada cuota recuerda de qué proveedor vino y cuándo se leyó: es lo que
        # permite luego distinguir precios directos de la casa de los de un
        # comparador (engine/quality.py).
        for market in fetched:
            for outcome in market.outcomes:
                if not outcome.source:
                    outcome.source = provider.name
                if outcome.fetched_at is None:
                    outcome.fetched_at = market.fetched_at
        raw_markets.extend(fetched)

    now = datetime.now(timezone.utc)
    seen_keys: set[str] = set()
    comparisons = []
    discarded = 0

    for grouped in group_by_event(raw_markets):
        market = best_odds_per_outcome(grouped)
        comparison = compare_market(market, bankroll, min_margin, round_step)
        comparisons.append(comparison)

        if comparison.margin > 0:
            comparison.flags, comparison.reliability = assess(
                market, comparison.margin, now, warn_margin, max_margin
            )
            if comparison.is_surebet and any(f in BLOCKING_FLAGS for f in comparison.flags):
                _invalidate(comparison)
                discarded += 1

        if not comparison.is_surebet:
            continue

        key = opportunity_key(comparison)
        seen_keys.add(key)
        entry = active_state.get(key)
        if isinstance(entry, dict):
            cycles = entry["cycles"] + 1
            previous_margin = entry["margin"]
            notified = entry["notified"]
        else:  # clave nueva (o formato antiguo sin normalizar)
            cycles = 1
            previous_margin = float(entry) if entry is not None else None
            notified = entry is not None

        confirmed = cycles >= confirm_cycles
        should_notify = confirmed and (
            not notified or abs(comparison.margin - previous_margin) >= MARGIN_CHANGE_THRESHOLD
        )
        active_state[key] = {
            "margin": comparison.margin,
            "cycles": cycles,
            "notified": notified or should_notify,
        }

        if not should_notify:
            continue

        row_id = save_opportunity(db_path, comparison)
        logger.info(
            "Surebet confirmada (#%s, %d ciclos, fiabilidad %s): %s margen %.2f%%",
            row_id,
            cycles,
            comparison.reliability,
            market.event,
            comparison.margin * 100,
        )
        await notify(format_alert(comparison))

    if discarded:
        logger.info("Descartadas %d falsas surebets por error de datos (ver engine/quality.py)", discarded)

    # Registra el estado de *todas* las comparaciones (sean o no surebet)
    # para el panel web, aparte del dedupe de arriba que solo mira surebets.
    save_comparisons(db_path, comparisons)

    # Las que ya no aparecen en este scan se consideran cerradas: si vuelven a
    # aparecer más adelante, se tratan como nuevas (y hay que confirmarlas otra vez).
    for key in list(active_state):
        if key not in seen_keys:
            del active_state[key]
