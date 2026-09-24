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

Los márgenes muy altos pero creíbles (VERIFY_MARGIN..MAX_MARGIN, 15-25 %) NO se
descartan: pueden ser reales, así que se marcan `margen_a_verificar` y
engine/scan.py los comprueba con una segunda lectura de las fuentes directas
en el mismo escaneo (o, si solo hay comparadores, exige más ciclos seguidos).
"""

import re
import statistics
from datetime import datetime, timedelta, timezone

from .models import Market, Outcome

# Fuentes que leen la propia casa (API o web de la casa): precio de referencia.
DIRECT_SOURCES = frozenset(
    {
        "altenar", "kambi", "sportium", "betfair", "winamax", "bwin", "bet777", "kirolbet",
        "pokerstars", "williamhill", "marcaapuestas", "zebet",
    }
)
# Comparadores: agregan casas ajenas y pueden ir desfasados (verificado hasta
# ~7 % en 1X2 en la hora previa al partido, ver README).
COMPARATOR_SOURCES = frozenset({"cuotasahora", "betexplorer"})

# Un margen por encima de esto es raro (BetBurger recomienda 0,5-5 %): se avisa
# pero se deja pasar tal cual.
WARN_MARGIN = 0.05
# Por encima de esto solo se avisa tras verificarlo (segunda lectura directa en
# el mismo escaneo, o más ciclos seguidos): puede ser real, pero es más probable
# un precio erróneo o desfasado.
VERIFY_MARGIN = 0.15
# Por encima de esto se considera un error de datos y se descarta.
MAX_MARGIN = 0.25
# Si hay alguna pata de comparador y el partido empieza en menos de esto, la
# cuota pudo cambiar (alineaciones) desde que el comparador la leyó.
NEAR_KICKOFF = timedelta(hours=2)
# Diferencia máxima entre la lectura más antigua y la más reciente de las patas
# de una misma surebet antes de avisar de que pueden estar desincronizadas.
MAX_LEG_SKEW = timedelta(minutes=10)

# Flags que descartan la surebet (error de datos, no oportunidad).
BLOCKING_FLAGS = frozenset(
    {"una_sola_casa", "mercado_incompleto", "margen_absurdo", "lectura_duplicada", "cuota_atipica"}
)

# Cuota atípica: una pata cuya cuota se aleja de la MEDIANA de lo que pagan las demás
# casas por el mismo resultado. Calibrado el 2026-09-21 con 2.500 patas de la caché
# de comparadores: la mediana del ratio cuota/mediana es 1,03 y el percentil 99 es
# 1,25; con estos umbrales solo salta el 0,2 % de las patas y casi todas eran
# lecturas erróneas (Betway en tenis a 16,0 frente a una mediana de 2,14; un Under a
# 4,0 frente a 2,0), que fabricaban "surebets" del 17-33 %.
OUTLIER_RATIO = 1.25  # la cuota es >= 1,25 veces la mediana del resto...
OUTLIER_PROB_DIFF = 0.08  # ...y su probabilidad implícita difiere en >= 8 puntos
# (esto último evita marcar cuotas altas de resultados improbables: 15,0 frente a 10,0
# es un ratio de 1,5 pero solo 3 puntos de probabilidad)
OUTLIER_MIN_OTHERS = 2  # con menos de 2 casas más no hay referencia (con 3 se colaban 3 casos de
# Betway en tenis que con 2 se cogen; con 2 no hubo ningún falso positivo más en la muestra)

# Coherencia de una fila casa-mercado: las probabilidades implícitas de TODOS los
# resultados de un mercado exhaustivo, según UNA casa, suman siempre más de 1 (su
# margen). Calibrado el 2026-09-21 con 35.738 filas de todas las fuentes: mediana
# 1,088, percentil 1 en 1,047 y NINGUNA fuente directa por debajo de 0,99; las 81
# filas por debajo de 0,99 eran todas de CuotasAhora (BTTS_HT, y las líneas 0 de
# OU/AH) con la tabla de otra pestaña leída por error. Con 0,97 no hay falsos
# positivos en esa muestra y sobra margen para redondeos.
COHERENCE_MIN = 0.97

FLAG_DESCRIPTIONS = {
    "una_sola_casa": "todas las patas son de la misma casa (error de datos)",
    "mercado_incompleto": "faltan resultados del mercado (error de datos)",
    "lectura_duplicada": "cuotas idénticas a las de otro mercado del mismo partido (tabla del comparador leída dos veces)",
    "cuota_atipica": "una cuota de comparador muy por encima de lo que pagan las demás casas (lectura errónea probable)",
    "cuota_destacada": "una cuota directa muy por encima de lo que pagan las demás casas: error de la casa o oportunidad real, comprueba en la web",
    "margen_absurdo": "margen por encima del máximo creíble (error de datos)",
    "margen_alto": "margen inusualmente alto: comprueba las cuotas en las casas",
    "margen_a_verificar": "margen muy alto: pendiente de verificar (comprueba las cuotas en las casas)",
    "margen_verificado": "margen muy alto confirmado con una segunda lectura directa de las casas",
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


# AH 0 y "Empate no apuesta" son el mismo mercado con dos nombres: que tengan las
# mismas cuotas es lo esperado, no una lectura duplicada.
_AH_ZERO = re.compile(r"^AH((?:_HT|_2H)?)_[+-]?0(?:\.0)?$")


def _canonical_type(market_type: str) -> str:
    match = _AH_ZERO.match(market_type)
    return f"DNB{match.group(1)}" if match else market_type


def has_comparator_leg(market: Market) -> bool:
    return any(o.source in COMPARATOR_SOURCES for o in market.outcomes)


def find_mirrored(candidates: list[tuple[Market, str]], references: dict[tuple, list[tuple[str, frozenset]]]) -> set[int]:
    """Índices de `candidates` cuyas patas (casa, cuota) aparecen TODAS, idénticas,
    en otro mercado del mismo partido: señal de que el comparador enseñaba la
    tabla de otra pestaña (1X2) cuando se leyó ésta.

    Verificado en el estado real del 2026-09-17: el 24 % de las comparaciones
    compartían casas y cuotas exactas con otro mercado del mismo partido (BTTS,
    BTTS_HT, OU_0 y DC con las cuotas 1/X del 1X2) y la mitad de las 28
    "surebets" eran eso. Es un fallo sistemático, así que repetir la lectura
    varios ciclos no lo detecta: por eso se mira la estructura, no el margen.

    `candidates` = (mercado final con la mejor cuota por resultado, tipo).
    `references` = por (deporte, partido), lista de (tipo canónico, conjunto de
    todos los pares (casa, cuota) leídos en ese mercado). El 1X2 nunca se marca:
    es la tabla que se lee sin cambiar de pestaña, la original.
    """
    mirrored: set[int] = set()
    for index, (market, key) in enumerate(candidates):
        canon = _canonical_type(market.market_type)
        if canon == "1X2":
            continue
        legs = frozenset((o.bookmaker, o.odds) for o in market.outcomes)
        # Candidata MIXTA (patas directas y de comparador): las directas nunca están en la
        # tabla de otro mercado, así que se mira solo lo que dice el comparador. Si sus
        # patas coinciden con las que esa misma casa tiene en el 1X2 (la tabla que se lee
        # sin cambiar de pestaña) es la misma lectura: p.ej. una "X al descanso" de 3.6 que
        # es en realidad la X del partido completo, cruzada con cuotas directas al descanso.
        comparator_legs = frozenset((o.bookmaker, o.odds) for o in market.outcomes if o.source in COMPARATOR_SOURCES)
        if comparator_legs and comparator_legs != legs and canon != "1X2":
            if any(other_canon == "1X2" and comparator_legs <= other_pairs for other_canon, other_pairs in references.get(key, ())):
                mirrored.add(index)
                continue
        if len(legs) < 2:
            continue
        for other_canon, other_pairs in references.get(key, ()):
            if other_canon != canon and legs <= other_pairs:
                mirrored.add(index)
                break
    return mirrored


def leg_outliers(
    all_outcomes: list[Outcome],
    legs: list[Outcome],
    ratio: float = OUTLIER_RATIO,
    prob_diff: float = OUTLIER_PROB_DIFF,
    min_others: int = OUTLIER_MIN_OTHERS,
) -> list[Outcome]:
    """Patas de `legs` (la mejor cuota de cada resultado) cuya cuota se sale de lo
    normal frente al resto de casas del mismo mercado (`all_outcomes`, todas las
    lecturas del grupo). Se compara con la mediana de las OTRAS casas para el mismo
    resultado; con la lectura directa de una casa si la hay, y si no la más baja.
    Necesita al menos `min_others` casas más: sin referencia no se juzga.
    """
    per_book: dict[tuple[str, str], tuple[float, bool]] = {}
    for outcome in all_outcomes:
        key = (outcome.bookmaker, outcome.name)
        direct = outcome.source in DIRECT_SOURCES
        current = per_book.get(key)
        if current is None or (direct and not current[1]):
            per_book[key] = (outcome.odds, direct)
        elif direct == current[1] and outcome.odds < current[0]:
            per_book[key] = (outcome.odds, direct)

    found = []
    for leg in legs:
        others = [odds for (book, name), (odds, _) in per_book.items() if name == leg.name and book != leg.bookmaker]
        if len(others) < min_others:
            continue
        median = statistics.median(others)
        if leg.odds / median >= ratio and 1 / median - 1 / leg.odds >= prob_diff:
            found.append(leg)
    return found


def leg_flags(all_outcomes: list[Outcome], legs: list[Outcome]) -> list[str]:
    """`cuota_atipica` (invalida la surebet) si alguna pata anómala viene de un
    comparador: no se puede comprobar aquí y los comparadores tienen fallos de
    lectura documentados. `cuota_destacada` (solo aviso) si la pata anómala es de una
    fuente directa: es lo que la casa ofrece de verdad, así que puede ser una
    oportunidad real."""
    outliers = leg_outliers(all_outcomes, legs)
    if not outliers:
        return []
    if any(o.source in COMPARATOR_SOURCES for o in outliers):
        return ["cuota_atipica"]
    return ["cuota_destacada"]


def drop_incoherent_rows(market: Market, min_sum: float = COHERENCE_MIN) -> tuple[Market, int]:
    """Quita del mercado las filas de COMPARADOR (una casa) cuyos resultados suman
    menos de `min_sum` en probabilidad implícita: una casa no ofrece eso, así que la
    fila es una lectura errónea (tabla de otra pestaña). Solo se juzgan filas
    completas (la casa da todos los resultados del mercado) y de comparador: una
    fila directa por debajo de 1 sería un error real de la casa, no de lectura. El
    doble oportunidad no se evalúa (sus resultados se solapan y suman ~2).
    Devuelve (mercado limpio, nº de filas quitadas); si no hay nada que quitar
    devuelve el mismo objeto."""
    if _canonical_type(market.market_type).split("_")[0] == "DC":
        return market, 0
    names = {o.name for o in market.outcomes}
    if len(names) < 2:
        return market, 0
    rows: dict[tuple[str, str], dict[str, float]] = {}
    for outcome in market.outcomes:
        if outcome.source not in COMPARATOR_SOURCES:
            continue
        row = rows.setdefault((outcome.bookmaker, outcome.source), {})
        row[outcome.name] = min(outcome.odds, row.get(outcome.name, outcome.odds))
    bad = {key for key, row in rows.items() if set(row) == names and sum(1 / v for v in row.values()) < min_sum}
    if not bad:
        return market, 0
    kept = [o for o in market.outcomes if (o.bookmaker, o.source) not in bad]
    return (
        Market(
            event=market.event,
            sport=market.sport,
            market_type=market.market_type,
            outcomes=kept,
            fetched_at=market.fetched_at,
            start_time=market.start_time,
        ),
        len(bad),
    )


# Flags que se añaden DESPUÉS de assess() (miran el grupo entero, no solo la surebet).
POST_FLAGS = frozenset({"lectura_duplicada", "cuota_atipica", "cuota_destacada"})


def _leg_sources(outcomes: list[Outcome]) -> set[str]:
    return {o.source for o in outcomes if o.source}


def assess(
    market: Market,
    margin: float,
    now: datetime | None = None,
    warn_margin: float = WARN_MARGIN,
    max_margin: float = MAX_MARGIN,
    verify_margin: float = VERIFY_MARGIN,
    verified: bool = False,
) -> tuple[list[str], str]:
    """Devuelve (flags, fiabilidad) de una surebet ya evaluada.

    `market` es el mercado final (mejor cuota por resultado), con sus
    `Outcome.source` / `fetched_at` rellenados por engine.scan. `verified`
    indica que engine.scan ya confirmó un margen alto con una segunda lectura
    directa: entonces se marca `margen_verificado` en vez de `margen_a_verificar`
    y no rebaja la fiabilidad.
    """
    now = now or datetime.now(timezone.utc)
    flags: list[str] = []

    if len({o.name for o in market.outcomes}) < min_outcomes(market.market_type):
        flags.append("mercado_incompleto")
    elif len({o.bookmaker for o in market.outcomes}) < 2:
        flags.append("una_sola_casa")
    if margin > max_margin:
        flags.append("margen_absurdo")
    elif margin > verify_margin:
        flags.append("margen_verificado" if verified else "margen_a_verificar")
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
    if "margen_a_verificar" in flags:
        return flags, "baja"
    if comparator_legs or "margen_alto" in flags:
        return flags, "media"
    return flags, "alta"
