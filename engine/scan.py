"""Un ciclo de escaneo (fetch -> cruce de eventos -> detección -> control de
calidad -> confirmación -> aviso), extraído de main.py para poder reutilizarlo
tanto desde el proceso de larga duración (VM + systemd, con el estado en
memoria) como desde un script de un solo disparo (GitHub Actions / tarea
programada local, con el estado cargado/guardado en un JSON entre ejecuciones).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from providers.base import OddsProvider
from storage.db import comparison_key, save_comparisons, save_opportunity

from .arbitrage import compare_market
from .health import SourceHealth
from .labels import kickoff_line, market_title, outcome_label, sport_name
from .matching import best_odds_per_outcome, event_key, group_by_event
from .quality import (
    BLOCKING_FLAGS,
    FLAG_DESCRIPTIONS,
    MAX_MARGIN,
    VERIFY_MARGIN,
    WARN_MARGIN,
    COHERENCE_MIN,
    POST_FLAGS,
    _canonical_type,
    assess,
    drop_incoherent_rows,
    find_mirrored,
    has_comparator_leg,
    leg_flags,
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


def _source_by_leg(comparison) -> str:
    return ", ".join(
        f"{o.bookmaker}←{o.source}" for o in comparison.market.outcomes if o.source
    )


def format_alert(comparison) -> str:
    """Un emoji por línea, al estilo de los mensajes reenviados del grupo
    origen (ver telegram_source/relay.py y su MENSAJE de ejemplo en
    tests/test_relay.py: "📈 ROI ...\\n🏠 Winamax\\n💵 Cuota @...") para que
    ambos tipos de aviso se vean del mismo estilo en el grupo de Telegram."""
    market = comparison.market
    lines = [
        f"🚨 Nueva surebet · {sport_name(market.sport)}",
        f"🎯 {market.event}",
        f"📌 {market_title(market.market_type, market.event, market.sport)}",
    ]
    lines.append(kickoff_line(market.start_time))
    lines.append(f"📈 Margen {comparison.margin * 100:.2f}%")
    for o in market.outcomes:
        label = outcome_label(market.market_type, o.name, market.event, market.sport)
        lines.append(f"🏠 {o.bookmaker}: {label} @{o.odds:.2f}")
    sources = _source_by_leg(comparison)
    if sources:
        lines.append(f"🔗 Fuentes: {sources}")
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


async def _fetch(
    provider: OddsProvider,
    sports: list[str],
    logger,
    sem: asyncio.Semaphore | None = None,
    timings: dict[str, dict] | None = None,
) -> list | None:
    # `timings[nombre]` = {"wait": s esperando turno del semáforo, "run": s leyendo de
    # verdad}: sin separarlos, con max_concurrency una fuente que espera turno parece
    # lenta cuando la lenta es otra. Se rellena también si la lectura falla.
    requested = time.perf_counter()
    started = requested
    try:
        # fetch_markets es síncrono y hace asyncio.run() por dentro (cada
        # provider lanza su propio Playwright); como run_scan_cycle ya corre
        # dentro de un event loop (main.py o scan_once_action.py), llamarlo
        # directamente aquí chocaría con ese loop en marcha ("asyncio.run()
        # cannot be called from a running event loop"). Se ejecuta en un hilo
        # aparte para darle un loop propio.
        # `sem` limita cuántos navegadores Chromium se lanzan a la vez (ver
        # `max_concurrency` en run_scan_cycle): sin límite, una máquina con
        # pocos núcleos satura la CPU con ~9 Chromium simultáneos y varios
        # providers acaban con timeout aunque cada uno por separado funcione
        # bien (confirmado en la VM de 2vCPU: load average >10 y timeouts en
        # Sportium/Betfair/Versus que no fallan en local).
        if sem is None:
            fetched = await asyncio.to_thread(provider.fetch_markets, sports)
        else:
            async with sem:
                started = time.perf_counter()
                fetched = await asyncio.to_thread(provider.fetch_markets, sports)
    except Exception:
        logger.exception("Fallo obteniendo datos de %s", provider.name)
        return None
    finally:
        if timings is not None:
            finished = time.perf_counter()
            timings[provider.name] = {"wait": started - requested, "run": finished - started}
    _stamp(provider, fetched)
    return fetched


async def _refine(
    provider: OddsProvider,
    sports: list[str],
    peer_markets: list,
    logger,
    sem: asyncio.Semaphore | None,
    timings: dict[str, dict],
) -> list:
    """Segunda pasada de un proveedor con `refines` (ver providers/base.py): se ejecuta
    cuando ya están leídas todas las fuentes, y aquí ya no hay nada más corriendo, así que
    el navegador tiene la máquina para él. Un fallo se registra y deja la primera pasada
    tal cual. Su tiempo se SUMA al de lectura de esa fuente."""
    started = time.perf_counter()
    try:
        if sem is None:
            extra = await asyncio.to_thread(provider.refine, sports, peer_markets)
        else:
            async with sem:
                started = time.perf_counter()
                extra = await asyncio.to_thread(provider.refine, sports, peer_markets)
    except Exception:
        logger.exception("Fallo en la segunda pasada de %s", provider.name)
        return []
    finally:
        entry = timings.setdefault(provider.name, {"wait": 0.0, "run": 0.0})
        entry["run"] += time.perf_counter() - started
    _stamp(provider, extra)
    return extra


def _build_comparisons(
    raw_markets: list,
    bankroll: float,
    min_margin: float,
    round_step: float,
    now: datetime,
    warn_margin: float,
    verify_margin: float,
    max_margin: float,
    stats: dict | None = None,
) -> list:
    comparisons = []
    references: dict[tuple, list] = {}
    for grouped in group_by_event(raw_markets):
        # Filas de comparador imposibles (suma de probabilidades < 1: tabla de otra
        # pestaña leída por error) fuera ANTES de calcular nada con ellas.
        grouped, dropped = drop_incoherent_rows(grouped)
        if stats is not None:
            stats["dropped_rows"] = stats.get("dropped_rows", 0) + dropped
        if not grouped.outcomes:
            continue
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
            # Cuotas atípicas frente a la mediana de las demás casas del mismo mercado
            # (necesita todas las lecturas del grupo, no solo la mejor de cada resultado).
            comparison.flags += leg_flags(grouped.outcomes, market.outcomes)
            if "cuota_destacada" in comparison.flags and comparison.reliability == "alta":
                comparison.reliability = "media"
            if "cuota_atipica" in comparison.flags:
                comparison.reliability = "baja"

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
            extra = [f for f in comparison.flags if f in POST_FLAGS]  # los de grupo se conservan
            comparison.flags, comparison.reliability = assess(
                comparison.market, comparison.margin, now, warn_margin, max_margin, verify_margin, verified=True
            )
            comparison.flags += extra
            if "cuota_destacada" in extra and comparison.reliability == "alta":
                comparison.reliability = "media"
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
    max_concurrency: int | None = None,
    health: SourceHealth | None = None,
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
    # max_concurrency limita cuántos Chromium corren a la vez cuando la máquina
    # tiene pocos núcleos (ver docstring de _fetch); None = sin límite, igual
    # que siempre.
    sem = asyncio.Semaphore(max_concurrency) if max_concurrency else None
    fetch_timings: dict[str, dict] = {}
    phases: dict[str, float] = {}
    cycle_start = time.perf_counter()

    # Fuentes aparcadas (engine/health.py): las de navegador que llevan ciclos seguidos
    # fallando o vacías no se leen esta vez; se reintentan cada vez más espaciadas.
    read_at = datetime.now(timezone.utc)
    parked: dict[str, float] = {}  # nombre -> minutos hasta el próximo intento
    to_read = []
    for provider in providers:
        wait = health.retry_in(provider.name, read_at) if health is not None and provider.parkable else None
        if wait is None:
            to_read.append(provider)
        else:
            parked[provider.name] = wait.total_seconds() / 60

    fetched_all = await asyncio.gather(
        *(_fetch(provider, sports, logger, sem, fetch_timings) for provider in to_read)
    )
    phases["lectura"] = time.perf_counter() - cycle_start
    for provider, fetched in zip(to_read, fetched_all):
        if fetched is not None:
            raw_by_provider[provider.name] = fetched
        if health is not None and provider.parkable:
            health.record(provider.name, good=bool(fetched), now=read_at)
    if health is not None:
        try:
            health.save()
        except OSError:
            logger.warning("No se pudo guardar el estado de las fuentes aparcadas", exc_info=True)

    # Segunda pasada de los proveedores que la tienen (PokerStars): con todas las demás
    # fuentes ya leídas se sabe qué partidos pueden cruzarse, y solo se gasta navegador en esos.
    step = time.perf_counter()
    refiners = [p for p in to_read if p.refines and p.name in raw_by_provider]
    if refiners:
        extras = await asyncio.gather(
            *(
                _refine(
                    p, sports,
                    [m for q in providers if q.name != p.name for m in raw_by_provider.get(q.name, [])],
                    logger, sem, fetch_timings,
                )
                for p in refiners
            )
        )
        for p, extra in zip(refiners, extras):
            raw_by_provider[p.name].extend(extra)
        phases["segunda_pasada"] = time.perf_counter() - step

    raw_markets = [m for p in providers for m in raw_by_provider.get(p.name, [])]
    sources = {
        p.name: {
            "ok": p.name in raw_by_provider,
            "markets": len(raw_by_provider.get(p.name, [])),
            "events": len({(m.sport, m.event) for m in raw_by_provider.get(p.name, [])}),
            "seconds": round(fetch_timings.get(p.name, {}).get("run", 0.0), 1),
            "wait_seconds": round(fetch_timings.get(p.name, {}).get("wait", 0.0), 1),
            **({"parked": True, "retry_in_minutes": round(parked[p.name])} if p.name in parked else {}),
        }
        for p in providers
    }
    for name, info in sources.items():
        if info.get("parked"):
            logger.info(
                "Fuente %s: aparcada (%d lecturas malas seguidas), próximo intento en %d min",
                name, health.streak(name), info["retry_in_minutes"],
            )
            continue
        logger.info(
            "Fuente %s: %d mercados de %d partidos en %.1fs%s%s",
            name,
            info["markets"],
            info["events"],
            info["seconds"],
            f" (esperó turno {info['wait_seconds']:.1f}s)" if info["wait_seconds"] >= 0.5 else "",
            "" if info["ok"] else " (FALLÓ)",
        )
    slowest = max(sources.items(), key=lambda item: item[1]["seconds"] + item[1]["wait_seconds"], default=None)
    if slowest is not None:
        logger.info(
            "Fuente más lenta: %s (%.1fs de lectura + %.1fs de espera de turno)",
            slowest[0],
            slowest[1]["seconds"],
            slowest[1]["wait_seconds"],
        )

    now = datetime.now(timezone.utc)
    args = (bankroll, min_margin, round_step, now, warn_margin, verify_margin, max_margin)
    stats: dict = {}
    step = time.perf_counter()
    comparisons = _build_comparisons(raw_markets, *args, stats)
    phases["cruce"] = time.perf_counter() - step
    if stats.get("dropped_rows"):
        logger.info(
            "Quitadas %d lecturas imposibles de comparadores (suma de probabilidades < %.2f: tabla de otra pestaña)",
            stats["dropped_rows"],
            COHERENCE_MIN,
        )
    step = time.perf_counter()
    comparisons = await _verify_high_margins(comparisons, providers, raw_by_provider, sports, args, logger)
    phases["verificacion"] = time.perf_counter() - step

    discarded = sum(1 for c in comparisons if c.margin > 0 and any(f in BLOCKING_FLAGS for f in c.flags))
    seen_keys: set[str] = set()
    notify_seconds = 0.0
    notified_count = 0
    step = time.perf_counter()

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
        # "notified" solo se marca True cuando el aviso de verdad sale (ver más abajo):
        # si `notify` falla (p.ej. timeout de red hacia Telegram), la surebet ya está
        # guardada en la base de datos, pero hay que seguir intentando avisar en el
        # próximo ciclo en vez de darla por avisada sin que el usuario la haya visto.
        active_state[key] = {
            "margin": comparison.margin,
            "cycles": cycles,
            "notified": notified,
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
        # Un fallo mandando el aviso (red, Telegram caído...) no debe tumbar el resto
        # del ciclo: la surebet ya quedó guardada arriba, y `save_comparisons`/el
        # volcado de estado que hace scan_once_action.py después de esta función
        # también deben ejecutarse pase lo que pase con este aviso concreto.
        notify_started = time.perf_counter()
        notified_count += 1
        try:
            await notify(format_alert(comparison))
        except Exception:
            logger.warning(
                "Fallo mandando el aviso de Telegram de la surebet #%s (ya guardada; se reintentará avisar en el próximo ciclo)",
                row_id,
                exc_info=True,
            )
        else:
            active_state[key]["notified"] = True
        finally:
            notify_seconds += time.perf_counter() - notify_started

    phases["avisos"] = notify_seconds
    phases["confirmacion"] = time.perf_counter() - step - notify_seconds

    if discarded:
        logger.info("Descartadas %d falsas surebets por error de datos (ver engine/quality.py)", discarded)

    # Registra el estado de *todas* las comparaciones (sean o no surebet)
    # para el panel web, aparte del dedupe de arriba que solo mira surebets.
    step = time.perf_counter()
    save_comparisons(db_path, comparisons)
    phases["guardado_bd"] = time.perf_counter() - step

    # Las que ya no aparecen en este scan se consideran cerradas: si vuelven a
    # aparecer más adelante, se tratan como nuevas (y hay que confirmarlas otra vez).
    for key in list(active_state):
        if key not in seen_keys:
            del active_state[key]

    phases["total"] = time.perf_counter() - cycle_start
    logger.info(
        "Tiempos del ciclo (%d mercados en bruto, %d comparaciones, %d avisos): %s",
        len(raw_markets),
        len(comparisons),
        notified_count,
        ", ".join(f"{name} {seconds:.1f}s" for name, seconds in phases.items()),
    )
    return {
        "sources": sources,
        "dropped_rows": stats.get("dropped_rows", 0),
        "phases": {name: round(seconds, 1) for name, seconds in phases.items()},
    }
