import difflib
import re
import unicodedata

from .models import Market, Outcome
from .team_aliases import canonical_team

# Umbral alto: solo como respaldo para equipos que no están en la tabla de
# alias (otra liga/deporte aún no cubierto). Un umbral bajo es lo que causó
# el bug original ("Barcelona" y "Celta" confundidos por similitud de texto).
FALLBACK_SIMILARITY_THRESHOLD = 0.85


def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _split_teams(event: str) -> tuple[str, str] | None:
    parts = event.split(" vs. ")
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _team_matches(a: str, b: str) -> bool:
    """Compara dos nombres de equipo. Usa la tabla de alias (engine/team_aliases.py)
    cuando ambos son reconocidos, ya que comparar por similitud de texto
    genérica confunde equipos con nombres parecidos por casualidad (p.ej.
    "Barcelona" y "Celta") o que comparten una palabra común (p.ej.
    "Atlético Madrid" y "Real Madrid" comparten "Madrid"). Si alguno de los
    dos no está en la tabla, se exige una similitud muy alta como respaldo,
    para no arriesgarse a fusionar partidos distintos.
    """
    norm_a, norm_b = _normalize(a), _normalize(b)
    canon_a, canon_b = canonical_team(norm_a), canonical_team(norm_b)
    if canon_a is not None and canon_b is not None:
        return canon_a == canon_b
    return _similarity(a, b) >= FALLBACK_SIMILARITY_THRESHOLD


def _events_match(a: str, b: str) -> bool:
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
    return _team_matches(home_a, home_b) and _team_matches(away_a, away_b)


def group_by_event(raw_markets: list[Market]) -> list[Market]:
    """Combina markets del mismo evento/mercado procedentes de distintos
    proveedores en un único Market con outcomes de varias casas, para que el
    motor de arbitraje pueda comparar cuotas entre ellas.
    """
    groups: list[Market] = []
    for market in raw_markets:
        target = next(
            (
                g
                for g in groups
                if g.sport == market.sport
                and g.market_type == market.market_type
                and _events_match(g.event, market.event)
            ),
            None,
        )
        if target is None:
            groups.append(
                Market(
                    event=market.event,
                    sport=market.sport,
                    market_type=market.market_type,
                    outcomes=list(market.outcomes),
                )
            )
        else:
            target.outcomes.extend(market.outcomes)
    return groups


def best_odds_per_outcome(market: Market) -> Market:
    """Cuando un mismo resultado (p.ej. "1") aparece en varias casas tras
    agrupar por evento, se queda con la cuota más alta de cada uno. Sin este
    paso, evaluate_market sumaría probabilidades implícitas de la misma
    selección repetida y el margen calculado sería incorrecto.
    """
    best: dict[str, Outcome] = {}
    for outcome in market.outcomes:
        current = best.get(outcome.name)
        if current is None or outcome.odds > current.odds:
            best[outcome.name] = outcome
    return Market(
        event=market.event,
        sport=market.sport,
        market_type=market.market_type,
        outcomes=list(best.values()),
    )
