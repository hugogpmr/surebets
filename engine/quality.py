"""Controles de calidad de una surebet candidata, antes de avisar.

Inspirado en cómo se defienden los servicios profesionales (BetBurger, etc.)
de los "arbs fantasma": cuotas que una casa ya cambió pero otra fuente sigue
mostrando. Aquí no se descarta nada por debajo del margen máximo: se
*etiquetan* las oportunidades (`flags`) y se resume en una fiabilidad
alta/media/baja para que el aviso y el panel las presenten con honestidad.

Solo `una_sola_casa`, `mercado_incompleto` y `margen_absurdo` invalidan la
surebet: no son una oportunidad rara sino un error de datos (verificado en el
estado real: había "surebets" del 35-60 % y alguna con una sola pata, por
faltar el resto de resultados del mercado).
"""

from datetime import datetime, timedelta, timezone

from .models import Market, Outcome

# Fuentes que leen la propia casa (API o web de la casa): precio de referencia.
DIRECT_SOURCES = frozenset({"altenar", "kambi", "sportium", "betfair", "winamax", "kirolbet"})
# Comparadores: agregan casas ajenas y pueden ir desfasados (verificado hasta
# ~7 % en 1X2 en la hora previa al partido, ver README).
COMPARATOR_SOURCES = frozenset({"cuotasahora", "betexplorer"})

# Un margen por encima de esto casi nunca es real (BetBurger recomienda
# 0,5-5 %): se avisa pero se deja pasar...
WARN_MARGIN = 0.05
# ...y por encima de esto se considera un error de datos y se descarta.
MAX_MARGIN = 0.15
# Si hay alguna pata de comparador y el partido empieza en menos de esto, la
# cuota pudo cambiar (alineaciones) desde que el comparador la leyó.
NEAR_KICKOFF = timedelta(hours=2)
# Diferencia máxima entre la lectura más antigua y la más reciente de las patas
# de una misma surebet antes de avisar de que pueden estar desincronizadas.
MAX_LEG_SKEW = timedelta(minutes=10)

# Flags que descartan la surebet (error de datos, no oportunidad).
BLOCKING_FLAGS = frozenset({"una_sola_casa", "mercado_incompleto", "margen_absurdo"})

FLAG_DESCRIPTIONS = {
    "una_sola_casa": "todas las patas son de la misma casa (error de datos)",
    "mercado_incompleto": "faltan resultados del mercado (error de datos)",
    "margen_absurdo": "margen imposible de creer (error de datos)",
    "margen_alto": "margen inusualmente alto: comprueba las cuotas en las casas",
    "solo_comparador": "todas las cuotas vienen de comparadores (pueden ir desfasadas)",
    "cerca_inicio": "empieza pronto y alguna cuota viene de un comparador",
    "cuotas_desfasadas": "las cuotas se leyeron con mucha diferencia de tiempo",
}


def min_outcomes(market_type: str) -> int:
    """Nº mínimo de resultados distintos para que el mercado esté completo.
    Los de tres resultados (1X2 con sus variantes de córners/tarjetas/mitades,
    hándicap europeo, doble oportunidad, "primero en...") necesitan 3; el resto
    de mercados que emite el sistema son de 2 (Más/Menos, Sí/No, hándicap
    asiático, DNB, Impar/Par). Un mercado al que le falta un resultado suma
    probabilidades por debajo de 1 y parece una surebet enorme sin serlo.
    """
    base = market_type.split("_")[0]
    if "1X2" in market_type or base in {"EH", "DC"} or market_type.startswith(("FIRST_", "LAST_")):
        return 3
    if "_FIRST" in market_type or "_LAST" in market_type:
        return 3
    return 2


def _leg_sources(outcomes: list[Outcome]) -> set[str]:
    return {o.source for o in outcomes if o.source}


def assess(
    market: Market,
    margin: float,
    now: datetime | None = None,
    warn_margin: float = WARN_MARGIN,
    max_margin: float = MAX_MARGIN,
) -> tuple[list[str], str]:
    """Devuelve (flags, fiabilidad) de una surebet ya evaluada.

    `market` es el mercado final (mejor cuota por resultado), con sus
    `Outcome.source` / `fetched_at` rellenados por engine.scan.
    """
    now = now or datetime.now(timezone.utc)
    flags: list[str] = []

    if len({o.name for o in market.outcomes}) < min_outcomes(market.market_type):
        flags.append("mercado_incompleto")
    elif len({o.bookmaker for o in market.outcomes}) < 2:
        flags.append("una_sola_casa")
    if margin > max_margin:
        flags.append("margen_absurdo")
    elif margin > warn_margin:
        flags.append("margen_alto")

    sources = _leg_sources(market.outcomes)
    comparator_legs = [o for o in market.outcomes if o.source in COMPARATOR_SOURCES]
    only_comparators = bool(market.outcomes) and len(comparator_legs) == len(market.outcomes)
    if only_comparators:
        flags.append("solo_comparador")

    if comparator_legs and market.start_time is not None:
        until_start = market.start_time - now
        if timedelta(0) < until_start < NEAR_KICKOFF:
            flags.append("cerca_inicio")

    if len(sources) > 1:
        times = [o.fetched_at for o in market.outcomes if o.fetched_at is not None]
        if len(times) > 1 and max(times) - min(times) > MAX_LEG_SKEW:
            flags.append("cuotas_desfasadas")

    if any(f in BLOCKING_FLAGS for f in flags):
        return flags, "baja"
    if only_comparators or "cerca_inicio" in flags or "cuotas_desfasadas" in flags:
        return flags, "baja"
    if comparator_legs or "margen_alto" in flags:
        return flags, "media"
    return flags, "alta"
