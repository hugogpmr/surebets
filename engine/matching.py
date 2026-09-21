import difflib
from datetime import datetime, timedelta
from functools import lru_cache

from .models import Market, Outcome
from .quality import DIRECT_SOURCES
from .team_aliases import COUNTRY_NAMES, GENERIC, canonical_team, squash
from .team_aliases import normalize as _normalize

# Umbral alto: solo como respaldo para equipos que no están en la tabla de
# alias (otra liga/deporte aún no cubierto). Un umbral bajo es lo que causó
# el bug original ("Barcelona" y "Celta" confundidos por similitud de texto).
FALLBACK_SIMILARITY_THRESHOLD = 0.85

# Dos mercados con hora de inicio conocida solo pueden ser el mismo partido si
# empiezan con menos de esta diferencia (holgura para husos/redondeos de cada
# casa). Evita fusionar dos partidos distintos con los mismos equipos (ida y
# vuelta, liga y copa) - un error que fabricaría surebets falsas.
MAX_START_DIFFERENCE = timedelta(hours=6)

# Las reglas sueltas de nombre (versiones abreviadas, ver _token_match) solo se
# aplican cuando ambas horas de inicio se conocen y difieren menos de esto: dos
# partidos distintos con equipos homónimos casi nunca empiezan a la vez.
LOOSE_START_TOLERANCE = timedelta(minutes=30)


@lru_cache(maxsize=None)
def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _split_teams(event: str) -> tuple[str, str] | None:
    parts = event.split(" vs. ")
    return (parts[0], parts[1]) if len(parts) == 2 else None


# Abreviaturas de una palabra que no se pueden deducir por texto.
_ABBREVIATIONS = frozenset({frozenset(("inter", "internacional"))})


def _token_equal(a: str, b: str, allow_initial: bool) -> bool:
    """Dos palabras son la misma si son iguales, una abreviatura conocida o, con
    `allow_initial`, una inicial ("A. Italiano"/"Audax Italiano"). NO se admiten
    prefijos genéricos: "San" no es "Santarritense" ni "Port" es "Portugal"."""
    if a == b or frozenset((a, b)) in _ABBREVIATIONS:
        return True
    return allow_initial and (len(a) == 1 or len(b) == 1) and a[0] == b[0]


def _token_match(a: str, b: str) -> bool:
    """Mismo equipo aunque una casa lo escriba más corto o abreviado ("Chievo" /
    "Chievo Verona", "Envigado" / "Envigado FC", "Dep. Capiata" / "Deportivo
    Capiata"). Es una regla SUELTA (puede juntar homónimos: "Plymouth" y "Plymouth
    Parkway"), por eso solo se usa con hora de inicio conocida y casi idéntica
    (ver group_by_event). Salvaguardas: las marcas (sub-23, filial, femenino,
    etiqueta entre paréntesis) deben coincidir; una selección solo casa por nombre
    exacto; y un nombre formado solo por palabras genéricas ("Independiente",
    "Sporting"...) no vale como abreviatura de uno más largo.
    """
    tokens_a, markers_a = squash(a)
    tokens_b, markers_b = squash(b)
    if markers_a != markers_b or not tokens_a or not tokens_b:
        return False
    if len(tokens_a) == len(tokens_b):
        return all(_token_equal(x, y, allow_initial=True) for x, y in zip(tokens_a, tokens_b))
    small, large = sorted((tokens_a, tokens_b), key=len)
    if " ".join(small) in COUNTRY_NAMES or all(token in GENERIC for token in small):
        return False
    remaining = list(large)
    for token in small:
        found = next((other for other in remaining if _token_equal(token, other, allow_initial=False)), None)
        if found is None:
            return False
        remaining.remove(found)
    return True


# Función pura y llamada miles de veces con los mismos pares de equipos por
# ciclo (cada partido aparece en decenas de mercados): se memoiza.
@lru_cache(maxsize=None)
def _team_matches(a: str, b: str, loose: bool = False) -> bool:
    """Compara dos nombres de equipo. Usa la tabla de alias (engine/team_aliases.py)
    cuando ambos son reconocidos, ya que comparar por similitud de texto
    genérica confunde equipos con nombres parecidos por casualidad (p.ej.
    "Barcelona" y "Celta") o que comparten una palabra común (p.ej.
    "Atlético Madrid" y "Real Madrid"). Si ninguno está en la tabla: mismas palabras
    significativas (o, con `loose`, una versión abreviada: `_token_match`) y, como
    último respaldo, una similitud de texto muy alta. Nunca se cruzan nombres con
    marcas distintas (femenino, sub-23, filial, "(Nairo)" de e-soccer), ni cuando
    solo uno está en la tabla (el otro podría ser un filial o un homónimo).
    """
    canon_a, canon_b = canonical_team(a), canonical_team(b)
    if canon_a is not None and canon_b is not None:
        return canon_a == canon_b
    tokens_a, markers_a = squash(a)
    tokens_b, markers_b = squash(b)
    if markers_a != markers_b:
        return False
    if " ".join(tokens_a) in COUNTRY_NAMES or " ".join(tokens_b) in COUNTRY_NAMES:
        return tokens_a == tokens_b  # "Australia" no es "Austria", aunque se parezcan
    if canon_a is None and canon_b is None:
        if tokens_a and tokens_a == tokens_b:
            return True
        if loose and _token_match(a, b):
            return True
    return _similarity(a, b) >= FALLBACK_SIMILARITY_THRESHOLD


def _events_match(a: str, b: str, loose: bool = False) -> bool:
    """Compara equipo local con local y visitante con visitante por
    separado, en vez del string completo del evento (comparar el string
    completo confundía partidos que comparten un equipo o una palabra, como
    "Atlético Madrid vs. Osasuna" con "Atlético Madrid vs. Real Madrid").
    """
    teams_a = _split_teams(a)
    teams_b = _split_teams(b)
    if teams_a is None or teams_b is None:
        return _similarity(a, b) >= FALLBACK_SIMILARITY_THRESHOLD
    home_a, away_a = teams_a
    home_b, away_b = teams_b
    return _team_matches(home_a, home_b, loose) and _team_matches(away_a, away_b, loose)


def event_key(event: str) -> tuple | str:
    """Clave estable de un partido (equipos normalizados y con alias) para
    indexar mercados del MISMO partido aunque el nombre del evento varíe un
    poco de un grupo a otro. Distinto de _events_match: aquí no se compara
    nada, solo se normaliza."""
    teams = _split_teams(event)
    if teams is None:
        return _normalize(event)
    return tuple(canonical_team(t) or _normalize(t) for t in teams)


def _starts_compatible(a: datetime | None, b: datetime | None) -> bool:
    """Si alguna de las dos horas de inicio es desconocida (comparadores) no se
    puede descartar el cruce: se decide solo por nombres, como siempre."""
    if a is None or b is None:
        return True
    return abs(a - b) <= MAX_START_DIFFERENCE


def _loose_ok(a: datetime | None, b: datetime | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= LOOSE_START_TOLERANCE


def group_by_event(raw_markets: list[Market]) -> list[Market]:
    """Combina markets del mismo evento/mercado procedentes de distintos
    proveedores en un único Market con outcomes de varias casas, para que el
    motor de arbitraje pueda comparar cuotas entre ellas.
    """
    # Los grupos se indexan por (deporte, tipo de mercado): solo un grupo del
    # mismo deporte y mercado puede fusionarse, así que comparar cada mercado
    # contra todos los grupos era trabajo tirado. Con ~27.000 mercados por
    # ciclo (Altenar + Kambi + comparadores) la búsqueda lineal tardaba ~110 s;
    # el resultado es idéntico (dentro de cada clave se conserva el orden de
    # creación, así que el primer grupo que casa es el mismo de siempre).
    groups: list[Market] = []
    by_key: dict[tuple[str, str], list[Market]] = {}
    for market in raw_markets:
        candidates = by_key.setdefault((market.sport, market.market_type), [])
        target = next(
            (
                g
                for g in candidates
                if _starts_compatible(g.start_time, market.start_time)
                and _events_match(g.event, market.event, _loose_ok(g.start_time, market.start_time))
            ),
            None,
        )
        if target is None:
            new_group = Market(
                event=market.event,
                sport=market.sport,
                market_type=market.market_type,
                outcomes=list(market.outcomes),
                start_time=market.start_time,
            )
            groups.append(new_group)
            candidates.append(new_group)
        else:
            target.outcomes.extend(market.outcomes)
            if target.start_time is None:
                target.start_time = market.start_time
    return groups


def best_odds_per_outcome(market: Market) -> Market:
    """Cuando un mismo resultado (p.ej. "1") aparece en varias casas tras
    agrupar por evento, se queda con la cuota más alta de cada uno. Sin este
    paso, evaluate_market sumaría probabilidades implícitas de la misma
    selección repetida y el margen calculado sería incorrecto.

    Antes de eso, si la MISMA casa aparece varias veces con el mismo
    resultado (porque la cubren varios proveedores: p.ej. Betway vía
    CuotasAhora y vía Altenar), manda la lectura de la fuente DIRECTA de la casa
    (la de un comparador puede ir desfasada) y, entre varias del mismo tipo, se
    queda con la cuota MÁS BAJA. Verificado en
    vivo el 2026-09-20 en la hora previa a un partido: los comparadores
    (CuotasAhora, BetExplorer) divergían entre sí y de las APIs directas de las
    casas hasta ~7% en el 1X2 (Paf: 2.80/2.55 en su propia API, 2.60/2.75 en
    BetExplorer, 2.88/2.45 en CuotasAhora), con cuotas moviéndose por las
    alineaciones. Una cuota vieja más alta cruzada con otra fresca fabrica
    surebets falsas. Usar la más baja es conservador: una surebet real sigue
    siéndolo con la cuota menor; una falsa deja de serlo.
    """
    direct = {(o.bookmaker, o.name) for o in market.outcomes if o.source in DIRECT_SOURCES}
    conservative: dict[tuple[str, str], Outcome] = {}
    for outcome in market.outcomes:
        key = (outcome.bookmaker, outcome.name)
        if key in direct and outcome.source not in DIRECT_SOURCES:
            continue  # la casa tiene lectura directa: la del comparador no cuenta
        current = conservative.get(key)
        if current is None or outcome.odds < current.odds:
            conservative[key] = outcome

    best: dict[str, Outcome] = {}
    for outcome in conservative.values():
        current = best.get(outcome.name)
        if current is None or outcome.odds > current.odds:
            best[outcome.name] = outcome
    return Market(
        event=market.event,
        sport=market.sport,
        market_type=market.market_type,
        outcomes=list(best.values()),
        start_time=market.start_time,
    )
