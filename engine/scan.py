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
from storage.db import comparison_key, save_comparisons, save_opportunity

from .arbitrage import compare_market, format_stakes
from .matching import best_odds_per_outcome, event_key, group_by_event
from .quality import (
    BLOCKING_FLAGS,
    FLAG_DESCRIPTIONS,
    MAX_MARGIN,
    VERIFY_MARGIN,
    WARN_MARGIN,
    _canonical_type,
    assess,
    find_mirrored,
    has_comparator_leg,
)

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
    if comparison.verification == "verificada":
        lines.append("✅ Margen muy alto verificado con una segunda lectura directa de las casas")
    elif comparison.verification == "pendiente":
        lines.append("🔎 Margen muy alto sin verificar en directo: solo se avisa tras aparecer en varios escaneos seguidos")
    for flag in comparison.flags:
        if flag not in ("margen_verificado", "margen_a_verificar"):  # ya explicados arriba
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


def _stamp(provider: OddsProvider, markets: list) -> None:
    """Cada cuota recuerda de qué proveedor vino y cuándo se leyó: es lo que
    permite luego distinguir precios directos de la casa de los de un
    comparador (engine/quality.py)."""
    for market in markets:
        for outcome in market.outcomes:
            if not outcome.source:
                outcome.source = provider.name
            if outcome.fetched_at is None:
                outcome.fetched_at = market.fetched_at


async def _fetch(provider: OddsProvider, sports: list[str], logger) -> list | None:
    try:
        # fetch_markets es síncrono y hace asyncio.run() por dentro (cada
        # provider lanza su propio Playwright); como run_scan_cycle ya corre
        # dentro de un event loop (main.py o scan_once_action.py), llamarlo
        # directamente aquí chocaría con ese loop en marcha ("asyncio.run()
        # cannot be called from a running event loop"). Se ejecuta en un hilo
        # aparte para darle un loop propio.
        fetched = await asyncio.to_thread(provider.fetch_markets, sports)
    except Exception:
        logger.exception("Fallo obteniendo datos de %s", provider.name)
        return None
    _stamp(provider, fetched)
    return fetched


def _build_comparisons(
    raw_markets: list,
    bankroll: float,
    min_margin: float,
    round_step: float,
    now: datetime,
    warn_margin: float,
    verify_margin: float,
    max_margin: float,
) -> list:
    comparisons = []
    references: dict[tuple, list] = {}
    for grouped in group_by_event(raw_markets):
        market = best_odds_per_outcome(grouped)
        comparison = compare_market(market, bankroll, min_margin, round_step)
        comparisons.append(comparison)
        # Todos los pares (casa, cuota) leídos en cada mercado, para detectar
        # tablas de un comparador leídas dos veces con otra etiqueta.
        references.setdefault((market.sport, event_key(market.event)), []).append(
            (_canonical_type(market.market_type), frozenset((o.bookmaker, o.odds) for o in grouped.outcomes))
        )
        if comparison.margin > 0:
            comparison.flags, comparison.reliability = assess(
                market, comparison.margin, now, warn_margin, max_margin, verify_margin
            )

    # Solo las candidatas con alguna pata de comparador pueden ser una lectura
    # duplicada (las APIs de Altenar/Kambi devuelven cada mercado por separado).
    to_check = [
        (i, (c.market, (c.market.sport, event_key(c.market.event))))
        for i, c in enumerate(comparisons)
        if c.margin > 0 and has_comparator_leg(c.market)
    ]
    mirrored = find_mirrored([item for _, item in to_check], references)
    for position in mirrored:
        comparison = comparisons[to_check[position][0]]
        comparison.flags.append("lectura_duplicada")
        comparison.reliability = "baja"

    for comparison in comparisons:
        if comparison.is_surebet and any(f in BLOCKING_FLAGS for f in comparison.flags):
            _invalidate(comparison)
    return comparisons



async def _verify_high_margins(
    comparisons: list,
    providers: list[OddsProvider],
    raw_by_provider: dict[str, list],
    sports: list[str],
    args: tuple,
    logger,
) -> list:
    """Verifica en el mismo escaneo las surebets de margen muy alto
    (`margen_a_verificar`): vuelve a leer las fuentes directas y baratas
    (`fast_recheck`: Altenar, Kambi) y recalcula. Una candidata cuyas patas
    vienen TODAS de esas fuentes y sigue siendo surebet con la lectura fresca
    queda `verificada`. Las que tienen alguna pata de comparador no se pueden
    comprobar aquí (releer un comparador cuesta minutos de navegador): quedan
    `pendiente`, y run_scan_cycle exigirá más ciclos seguidos antes de avisar.
    Si tras la relectura la candidata ya no es surebet, desaparece sola.
    Devuelve la lista de comparaciones final (la fresca, si hubo relectura).
    """
    candidates = {
        comparison_key(c): c for c in comparisons if c.is_surebet and "margen_a_verificar" in c.flags
    }
    if not candidates:
        return comparisons

    rechecked = [p for p in providers if p.fast_recheck]
    names = {p.name for p in rechecked}
    involved = {o.source for c in candidates.values() for o in c.market.outcomes} & names
    if involved:
        logger.info(
            "Verificando %d surebets de margen muy alto con una segunda lectura de: %s",
            len(candidates),
            ", ".join(sorted(involved)),
        )
        refreshed = False
        for provider in rechecked:
            if provider.name not in involved:
                continue
            fresh = await _fetch(provider, sports, logger)
            if fresh is not None:
                raw_by_provider[provider.name] = fresh
                refreshed = True
        if refreshed:
            raw_markets = [m for p in providers for m in raw_by_provider.get(p.name, [])]
            comparisons = _build_comparisons(raw_markets, *args)

    _, _, _, now, warn_margin, verify_margin, max_margin = args
    fresh_by_key = {comparison_key(c): c for c in comparisons}
    refuted = 0
    for key in candidates:
        comparison = fresh_by_key.get(key)
        if comparison is None or not comparison.is_surebet:
            refuted += 1
            continue
        legs = {o.source for o in comparison.market.outcomes}
        if involved and legs <= names and "margen_a_verificar" in comparison.flags:
            comparison.verification = "verificada"
            comparison.flags, comparison.reliability = assess(
                comparison.market, comparison.margin, now, warn_margin, max_margin, verify_margin, verified=True
            )
        else:
            comparison.verification = "pendiente"
    if refuted:
        logger.info("La segunda lectura no confirmó %d surebets de margen muy alto: descartadas", refuted)
    return comparisons


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
    verify_margin: float = VERIFY_MARGIN,
    verify_cycles: int = 3,
) -> dict:
    """Ejecuta un ciclo de escaneo. Muta `active_state` in-place (clave ->
    {margin, cycles, notified}) para que el caller pueda persistirlo entre
    ejecuciones si hace falta. Devuelve el estado de cada fuente
    ({"sources": {nombre: {"ok", "markets", "events"}}}): una fuente con 0
    mercados o `ok=False` es señal de que algo va mal.

    Una surebet solo se avisa (y se guarda en el histórico) cuando lleva
    `confirm_cycles` escaneos seguidos apareciendo: es lo que filtra las cuotas
    que parpadean un instante o que un comparador tenía ya desfasadas. Las de
    margen muy alto (> `verify_margin`) se verifican además con una segunda
    lectura directa en el mismo escaneo (avisan enseguida si se confirman) o,
    si no se pueden verificar así, necesitan `verify_cycles` escaneos seguidos.
    """
    raw_by_provider: dict[str, list] = {}
    # Las fuentes se leen A LA VEZ (cada una en su hilo, con su propio navegador si lo
    # necesita): en serie, sumar bwin y Winamax a Altenar/Kambi/Sportium/Betfair
    # alargaba el ciclo por encima de lo que aguanta un escaneo cada pocos minutos.
    fetched_all = await asyncio.gather(*(_fetch(provider, sports, logger) for provider in providers))
    for provider, fetched in zip(providers, fetched_all):
        if fetched is not None:
            raw_by_provider[provider.name] = fetched
    raw_markets = [m for p in providers for m in raw_by_provider.get(p.name, [])]
    sources = {
        p.name: {
            "ok": p.name in raw_by_provider,
            "markets": len(raw_by_provider.get(p.name, [])),
            "events": len({(m.sport, m.event) for m in raw_by_provider.get(p.name, [])}),
        }
        for p in providers
    }
    for name, info in sources.items():
        logger.info("Fuente %s: %d mercados de %d partidos%s", name, info["markets"], info["events"], "" if info["ok"] else " (FALLÓ)")

    now = datetime.now(timezone.utc)
    args = (bankroll, min_margin, round_step, now, warn_margin, verify_margin, max_margin)
    comparisons = _build_comparisons(raw_markets, *args)
    comparisons = await _verify_high_margins(comparisons, providers, raw_by_provider, sports, args, logger)

    discarded = sum(1 for c in comparisons if c.margin > 0 and any(f in BLOCKING_FLAGS for f in c.flags))
    seen_keys: set[str] = set()

    for comparison in comparisons:
        if not comparison.is_surebet:
            continue
        market = comparison.market
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

        if comparison.verification == "verificada":
            needed = 1  # ya leída dos veces en directo dentro de este escaneo
        elif comparison.verification == "pendiente":
            needed = max(confirm_cycles, verify_cycles)
        else:
            needed = confirm_cycles
        confirmed = cycles >= needed
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
            "Surebet confirmada (#%s, %d ciclos, fiabilidad %s%s): %s margen %.2f%%",
            row_id,
            cycles,
            comparison.reliability,
            f", {comparison.verification}" if comparison.verification else "",
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

    return {"sources": sources}
