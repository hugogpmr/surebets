"""Un ciclo de escaneo (fetch -> cruce de eventos -> detección -> control de
calidad -> confirmación -> aviso), extraído de main.py para poder reutilizarlo
tanto desde el proceso de larga duración (VM + systemd, con el estado en
memoria) como desde un script de un solo disparo (GitHub Actions / tarea
programada local, con el estado cargado/guardado en un JSON entre ejecuciones).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from providers.base import OddsProvider
from storage.db import comparison_key, save_comparisons, save_opportunity

from .arbitrage import compare_market
from .alerts import SourceAlerts
from .backtest import SurebetLog
from .health import SourceHealth
from .handicap import ASIAN, check_whole_handicaps
from .labels import kickoff_line, market_title, outcome_label, push_note, sport_name
from .matching import best_odds_per_outcome, event_key, group_by_event
from .peers import PeerEvents
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

# Avisos agrupados (2026-10-02). Antes: un mensaje por surebet y otro cada vez que el margen se
# movía 0,5 puntos (subiendo o bajando); el 1-oct salieron 290 avisos de 86 partidos en 8 h, hasta
# 26 del mismo. Ahora:
# - un mensaje por partido con todas sus surebets nuevas (como mucho MAX_PER_MESSAGE);
# - una ya avisada solo se repite si su margen SUBE al menos REALERT_MARGIN_INCREASE;
# - una ya avisada que deja de verse se recuerda REALERT_COOLDOWN: si vuelve en ese tiempo (una
#   fuente que falló un ciclo, una cuota que parpadea) no se avisa otra vez.
REALERT_MARGIN_INCREASE = 0.01
REALERT_COOLDOWN = timedelta(minutes=60)
MAX_PER_MESSAGE = 6
MAX_MESSAGE_CHARS = 3800  # Telegram corta a 4096

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
            for extra in ("since", "notified_margin", "gone_at"):
                if value.get(extra) is not None:
                    state[key][extra] = value[extra]
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
    lines += _alert_details(comparison)
    return "\n".join(lines)


def format_event_alert(
    comparisons: list, improved: dict[int, float] | None = None, still_active: list | None = None
) -> str:
    """Un solo mensaje con varias surebets del MISMO partido, de mayor a menor margen.
    `improved` = {id(comparison): margen avisado antes} para las que se repiten porque mejoran.
    `still_active` = surebets del mismo partido ya avisadas que siguen saliendo EN ESTA MISMA
    LECTURA (no se repiten enteras: una línea corta cada una, al final)."""
    improved = improved or {}
    still_active = still_active or []
    if len(comparisons) == 1 and not improved:
        text = format_alert(comparisons[0])
    else:
        text = _format_group(comparisons, improved)
    if still_active:
        text += "\n" + "\n".join(_still_active_lines(still_active))
    return text


def _still_active_lines(comparisons: list) -> list[str]:
    lines = ["➖➖➖", "Siguen activas en este partido:"]
    for comparison in sorted(comparisons, key=lambda c: -c.margin)[:MAX_PER_MESSAGE]:
        market = comparison.market
        books = " / ".join(dict.fromkeys(o.bookmaker for o in market.outcomes))
        title = market_title(market.market_type, market.event, market.sport)
        lines.append(f"• {title} · {comparison.margin * 100:.2f}% ({books})")
    if len(comparisons) > MAX_PER_MESSAGE:
        lines.append(f"• y {len(comparisons) - MAX_PER_MESSAGE} más en el panel")
    return lines


def _format_group(comparisons: list, improved: dict[int, float]) -> str:
    ordered = sorted(comparisons, key=lambda c: -c.margin)
    first = ordered[0].market
    count = len(ordered)
    header = f"🚨 {count} surebets" if count > 1 else "🚨 Surebet mejorada"
    lines = [f"{header} · {sport_name(first.sport)}", f"🎯 {first.event}", kickoff_line(first.start_time)]
    shown = 0
    for comparison in ordered[:MAX_PER_MESSAGE]:
        market = comparison.market
        title = market_title(market.market_type, market.event, market.sport)
        before = improved.get(id(comparison))
        trend = f" (antes {before * 100:.2f}%)" if before is not None else ""
        block = ["➖➖➖", f"📌 {title} · 📈 {comparison.margin * 100:.2f}%{trend}", *_alert_details(comparison)]
        if shown and len("\n".join(lines + block)) > MAX_MESSAGE_CHARS:
            break
        lines += block
        shown += 1
    if shown < count:
        lines.append(f"➕ {count - shown} más en el panel")
    return "\n".join(lines)


def _alert_details(comparison) -> list[str]:
    """Patas, notas y avisos de calidad de una surebet (todo menos la cabecera)."""
    market = comparison.market
    lines = []
    for o in market.outcomes:
        label = outcome_label(market.market_type, o.name, market.event, market.sport)
        lines.append(f"🏠 {o.bookmaker}: {label} @{o.odds:.2f}")
    note = push_note(market.market_type, market.event, market.sport)
    if note:
        lines.append(note)
    sources = _source_by_leg(comparison)
    if sources:
        lines.append(f"🔗 Fuentes: {sources}")
    if comparison.verification == "verificada":
        lines.append("✅ Margen muy alto verificado con una segunda lectura directa de las casas")
    elif comparison.verification == "pendiente":
        lines.append("🔎 Margen muy alto sin verificar en directo: solo se avisa tras aparecer en varios escaneos seguidos")
    if "handicap_asiatico_ok" in comparison.flags:
        lines.append(f"✅ {FLAG_DESCRIPTIONS['handicap_asiatico_ok'].capitalize()}")
    for flag in comparison.flags:
        if flag not in ("margen_verificado", "margen_a_verificar", "handicap_asiatico_ok"):  # ya explicados arriba
            lines.append(f"⚠️ {FLAG_DESCRIPTIONS.get(flag, flag)}")
    return lines


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


async def _call(
    provider: OddsProvider,
    method,
    args: tuple,
    sem: asyncio.Semaphore | None,
    executor: ThreadPoolExecutor | None,
    timings: dict[str, dict] | None,
):
    """Ejecuta `method(*args)` (síncrono) de un proveedor en un hilo y anota en
    `timings[nombre]` {"wait": lo que tardó en EMPEZAR (turno del semáforo + hilo libre),
    "run": lo que tardó de verdad}. Se mide dentro del propio hilo: medirlo desde fuera
    contaba la cola como si fuera lectura (medido en la VM el 2026-09-28: un proveedor que no
    hace nada marcaba 44 s). Se anota también si la lectura falla.

    Los métodos hacen asyncio.run() por dentro (cada proveedor lanza su propio Playwright);
    como run_scan_cycle ya corre dentro de un event loop, llamarlos directamente chocaría con
    él, así que van en un hilo con su propio loop.

    Solo los proveedores con navegador (`uses_browser`) pasan por `sem`: sin límite, una
    máquina de pocos núcleos satura la CPU con ~9 Chromium a la vez y varios acaban con
    timeout aunque cada uno por separado funcione bien (VM de 2 vCPU: load average >10).
    Las fuentes por httpx no esperan a nadie. `executor` es un pool con hilo para cada
    fuente: el pool por defecto de asyncio (min(32, cpus + 4) = 6 en la VM) dejaba a las
    demás en cola, y Altenar/Kambi, las más lentas, empezaban unos 30 s tarde."""
    box: dict[str, float] = {}
    requested = time.perf_counter()

    def call():
        box["start"] = time.perf_counter()
        try:
            return method(*args)
        finally:
            box["end"] = time.perf_counter()

    async def run():
        if executor is None:
            return await asyncio.to_thread(call)
        return await asyncio.get_running_loop().run_in_executor(executor, call)

    try:
        if sem is not None and provider.uses_browser:
            async with sem:
                return await run()
        return await run()
    finally:
        if timings is not None:
            start = box.get("start", requested)
            entry = timings.setdefault(provider.name, {"wait": 0.0, "run": 0.0})
            entry["wait"] += start - requested
            entry["run"] += box.get("end", time.perf_counter()) - start


async def _fetch(
    provider: OddsProvider,
    sports: list[str],
    logger,
    sem: asyncio.Semaphore | None = None,
    timings: dict[str, dict] | None = None,
    executor: ThreadPoolExecutor | None = None,
) -> list | None:
    try:
        fetched = await _call(provider, provider.fetch_markets, (sports,), sem, executor, timings)
    except Exception:
        logger.exception("Fallo obteniendo datos de %s", provider.name)
        return None
    _stamp(provider, fetched)
    return fetched


async def _refine(
    provider: OddsProvider,
    sports: list[str],
    peer_markets: list,
    logger,
    sem: asyncio.Semaphore | None,
    timings: dict[str, dict],
    executor: ThreadPoolExecutor | None = None,
) -> list:
    """Segunda pasada de un proveedor con `refines` (ver providers/base.py). Un fallo se
    registra y deja la primera pasada tal cual. Su tiempo se SUMA al de esa fuente."""
    try:
        extra = await _call(provider, provider.refine, (sports, peer_markets), sem, executor, timings)
    except Exception:
        logger.exception("Fallo en la segunda pasada de %s", provider.name)
        return []
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
    # Hándicap de línea entera: fuera las casas que lo dan europeo (3 vías), ver engine/handicap.py.
    groups, handicap_verdicts, dropped_3way = check_whole_handicaps(group_by_event(raw_markets))
    if stats is not None:
        stats["dropped_3way_handicap"] = stats.get("dropped_3way_handicap", 0) + dropped_3way
    for grouped in groups:
        verdicts = handicap_verdicts.get(id(grouped))
        # Filas de comparador imposibles (suma de probabilidades < 1: tabla de otra
        # pestaña leída por error) fuera ANTES de calcular nada con ellas.
        grouped, dropped = drop_incoherent_rows(grouped)
        if stats is not None:
            stats["dropped_rows"] = stats.get("dropped_rows", 0) + dropped
        if not grouped.outcomes:
            continue
        market = best_odds_per_outcome(grouped)
        comparison = compare_market(market, bankroll, min_margin, round_step)
        comparison.readings = grouped.outcomes
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
            if verdicts is not None:
                if all(verdicts.get(o.bookmaker) == ASIAN for o in market.outcomes):
                    comparison.flags.append("handicap_asiatico_ok")
                else:
                    comparison.flags.append("handicap_sin_comprobar")
                    if comparison.reliability == "alta":
                        comparison.reliability = "media"

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
    executor: ThreadPoolExecutor | None = None,
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
            fresh = await _fetch(provider, sports, logger, executor=executor)
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


async def _run_scan_cycle(
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
    peers: PeerEvents | None = None,
    source_alerts: SourceAlerts | None = None,
    notify_admin: NotifyFn | None = None,
    backtest: SurebetLog | None = None,
    executor: ThreadPoolExecutor | None = None,
    verify_min_age: timedelta | None = None,
    log_sources: bool = True,
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

    `verify_min_age` (modo continuo, engine/live.py): en vez de `verify_cycles` escaneos, las de
    margen muy alto sin verificar deben llevar al menos ese tiempo apareciendo. Con un análisis
    por minuto, "3 escaneos seguidos" serían 3 minutos con los mismos datos de un comparador que
    se refresca cada ~20: no demostraría nada.
    """
    raw_by_provider: dict[str, list] = {}
    # Las fuentes se leen A LA VEZ (cada una en su hilo, con su propio navegador si lo
    # necesita): en serie, sumar bwin y Winamax a Altenar/Kambi/Sportium/Betfair
    # alargaba el ciclo por encima de lo que aguanta un escaneo cada pocos minutos.
    # max_concurrency limita cuántos Chromium corren a la vez cuando la máquina
    # tiene pocos núcleos (solo cuenta para las fuentes con navegador, ver docstring de
    # _call); None = sin límite.
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

    # Los proveedores con segunda pasada (PokerStars) necesitan saber qué partidos lista otra
    # casa. Si hay datos del ciclo anterior (engine/peers.py) la hacen YA, nada más terminar
    # su primera pasada y mientras Altenar y Kambi siguen leyendo; si no, esperan a que
    # terminen las demás fuentes (más abajo).
    previous_peers = peers.load(read_at) if peers is not None and any(p.refines for p in to_read) else None
    refined_early: set[str] = set()

    async def read(provider: OddsProvider) -> list | None:
        fetched = await _fetch(provider, sports, logger, sem, fetch_timings, executor)
        if fetched is None or not provider.refines or previous_peers is None:
            return fetched
        logger.info(
            "%s: segunda pasada adelantada con los partidos del ciclo anterior (hace %.0f min)",
            provider.name, (peers.age(read_at) or timedelta(0)).total_seconds() / 60,
        )
        fetched.extend(await _refine(provider, sports, previous_peers, logger, sem, fetch_timings, executor))
        refined_early.add(provider.name)
        return fetched

    fetched_all = await asyncio.gather(*(read(provider) for provider in to_read))
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

    # Segunda pasada de los que no pudieron adelantarla (primer ciclo o datos viejos): con todas
    # las demás fuentes ya leídas se sabe qué partidos pueden cruzarse. Aquí ya no hay nada más
    # corriendo, así que el navegador tiene la máquina para él.
    step = time.perf_counter()
    refiners = [p for p in to_read if p.refines and p.name in raw_by_provider and p.name not in refined_early]
    if refiners:
        extras = await asyncio.gather(
            *(
                _refine(
                    p, sports,
                    [m for q in providers if q.name != p.name for m in raw_by_provider.get(q.name, [])],
                    logger, sem, fetch_timings, executor,
                )
                for p in refiners
            )
        )
        for p, extra in zip(refiners, extras):
            raw_by_provider[p.name].extend(extra)
        phases["segunda_pasada"] = time.perf_counter() - step

    if peers is not None:
        try:
            peers.save([m for p in providers if not p.refines for m in raw_by_provider.get(p.name, [])], read_at)
        except OSError:
            logger.warning("No se pudo guardar los partidos de este ciclo para el siguiente", exc_info=True)

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
    for name, info in sources.items() if log_sources else ():
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
    if source_alerts is not None and notify_admin is not None:
        alert = source_alerts.update(sources)
        if alert:
            try:
                await notify_admin(alert)
            except Exception:
                logger.warning("No se pudo enviar el aviso de fuentes", exc_info=True)
    slowest = max(sources.items(), key=lambda item: item[1]["seconds"] + item[1]["wait_seconds"], default=None)
    if slowest is not None and log_sources:
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
    comparisons = await _verify_high_margins(comparisons, providers, raw_by_provider, sports, args, logger, executor)
    phases["verificacion"] = time.perf_counter() - step

    discarded = sum(1 for c in comparisons if c.margin > 0 and any(f in BLOCKING_FLAGS for f in c.flags))
    seen_keys: set[str] = set()
    notify_seconds = 0.0
    notified_count = 0
    pending: dict[tuple[str, str], list] = {}
    step = time.perf_counter()

    for comparison in comparisons:
        if not comparison.is_surebet:
            continue
        market = comparison.market
        key = opportunity_key(comparison)
        seen_keys.add(key)
        entry = active_state.get(key)
        if isinstance(entry, dict):
            returning = entry.get("gone_at") is not None  # ya avisada, desapareció y vuelve
            cycles = 1 if returning else entry["cycles"] + 1
            notified = entry["notified"]
            notified_margin = entry.get("notified_margin", entry["margin"])
            since = now.isoformat() if returning else entry.get("since") or now.isoformat()
        else:  # clave nueva (o formato antiguo sin normalizar)
            cycles = 1
            notified = entry is not None
            notified_margin = float(entry) if entry is not None else None
            since = now.isoformat()

        if comparison.verification == "verificada":
            needed = 1  # ya leída dos veces en directo dentro de este escaneo
        elif comparison.verification == "pendiente":
            needed = max(confirm_cycles, verify_cycles)
        else:
            needed = confirm_cycles
        confirmed = cycles >= needed
        if comparison.verification == "pendiente" and verify_min_age is not None:
            confirmed = cycles >= confirm_cycles and now - datetime.fromisoformat(since) >= verify_min_age
        should_notify = confirmed and (
            not notified or comparison.margin >= notified_margin + REALERT_MARGIN_INCREASE - 1e-9
        )
        # "notified" solo se marca True cuando el aviso de verdad sale (ver más abajo):
        # si `notify` falla (p.ej. timeout de red hacia Telegram), la surebet ya está
        # guardada en la base de datos, pero hay que seguir intentando avisar en el
        # próximo ciclo en vez de darla por avisada sin que el usuario la haya visto.
        active_state[key] = {
            "margin": comparison.margin,
            "cycles": cycles,
            "notified": notified,
            "since": since,
        }
        if notified and notified_margin is not None:
            active_state[key]["notified_margin"] = notified_margin

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
        pending.setdefault((market.sport, market.event), []).append(
            (key, comparison, notified_margin if notified else None)
        )

    # Un mensaje por partido (ver REALERT_* arriba). Un fallo mandando un aviso (red, Telegram
    # caído...) no debe tumbar el resto del ciclo: las surebets ya quedaron guardadas arriba y se
    # reintentará avisarlas en el próximo ciclo (`notified` solo pasa a True si el mensaje sale).
    messages = 0
    for event_key_, group in pending.items():
        notify_started = time.perf_counter()
        notified_count += len(group)
        improved = {id(c): before for _, c, before in group if before is not None}
        in_message = {key for key, _, _ in group}
        still_active = [
            c
            for c in comparisons
            if c.is_surebet
            and (c.market.sport, c.market.event) == event_key_
            and opportunity_key(c) not in in_message
            and active_state.get(opportunity_key(c), {}).get("notified")
        ]
        try:
            await notify(format_event_alert([c for _, c, _ in group], improved, still_active))
            messages += 1
        except Exception:
            logger.warning(
                "Fallo mandando el aviso de Telegram de %s (ya guardado; se reintentará en el próximo ciclo)",
                group[0][1].market.event,
                exc_info=True,
            )
        else:
            for key, comparison, _ in group:
                active_state[key]["notified"] = True
                active_state[key]["notified_margin"] = comparison.margin
        finally:
            notify_seconds += time.perf_counter() - notify_started
    if pending:
        logger.info("Avisos: %d surebets en %d mensajes", notified_count, messages)

    phases["avisos"] = notify_seconds
    phases["confirmacion"] = time.perf_counter() - step - notify_seconds

    # Histórico para el backtest (engine/backtest.py). Un fallo aquí nunca debe tumbar el ciclo.
    if backtest is not None:
        step = time.perf_counter()
        try:
            summary = backtest.record_cycle(
                comparisons,
                sources,
                now,
                min_margin,
                notified_keys={k for k, v in active_state.items() if v.get("notified")},
            )
            logger.info(
                "Backtest: %d episodios nuevos, %d que siguen, %d cerrados",
                summary["abiertos"], summary["actualizados"], summary["cerrados"],
            )
        except Exception:
            logger.warning("No se pudo guardar el histórico del backtest", exc_info=True)
        phases["backtest"] = time.perf_counter() - step

    if discarded:
        logger.info("Descartadas %d falsas surebets por error de datos (ver engine/quality.py)", discarded)

    # Registra el estado de *todas* las comparaciones (sean o no surebet)
    # para el panel web, aparte del dedupe de arriba que solo mira surebets.
    step = time.perf_counter()
    save_comparisons(db_path, comparisons)
    phases["guardado_bd"] = time.perf_counter() - step

    # Las que ya no aparecen se consideran cerradas, salvo las ya avisadas, que se recuerdan
    # REALERT_COOLDOWN para no avisarlas otra vez si solo han parpadeado (ver arriba).
    for key in list(active_state):
        entry = active_state[key]
        if key in seen_keys:
            entry.pop("gone_at", None)
            continue
        if not entry.get("notified"):
            del active_state[key]
            continue
        gone_at = entry.setdefault("gone_at", now.isoformat())
        if now - datetime.fromisoformat(gone_at) > REALERT_COOLDOWN:
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


async def run_scan_cycle(providers: list[OddsProvider], sports: list[str], *args, **kwargs) -> dict:
    """Ejecuta un ciclo de escaneo (parámetros y resultado: ver `_run_scan_cycle`). Crea el
    pool de hilos del ciclo con hilo de sobra para cada fuente y su segunda pasada: el pool por
    defecto de asyncio tiene solo min(32, cpus + 4) hilos (6 en una VM de 2 vCPU) y dejaba a
    Altenar y Kambi, las más lentas, ~30 s en cola detrás de los navegadores."""
    executor = ThreadPoolExecutor(max_workers=max(2 * len(providers), 8), thread_name_prefix="fuente")
    try:
        return await _run_scan_cycle(providers, sports, *args, executor=executor, **kwargs)
    finally:
        executor.shutdown(wait=False)
