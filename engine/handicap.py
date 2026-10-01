"""Hándicap con línea entera (AH -1, +2, 0...): asiático o europeo.

Asiático (2 opciones): si la diferencia cae justo en la línea, la apuesta es nula y se
devuelve, así que "A +1" en una casa y "B -1" en otra es una surebet real. Europeo
(3 opciones, con "Empate"): ese mismo resultado es el empate del hándicap y las DOS patas
pierden. Si una casa (o el comparador que la lee) da el europeo sin su "Empate", la
"surebet" es falsa - pasó con 888sport/Betfair en casasdeapuestas (ver
providers/casasdeapuestas.py:_THREE_WAY_INTEGER_BOOKIES).

Aquí se comprueba con las propias cuotas de cada casa, en cada escaneo:
- Sus dos lados de la misma línea: en un asiático suman >1 en probabilidad implícita
  (su margen; medido 2026-10-01 en 13 casas: mínimo 1,048); en un europeo sin "Empate"
  falta la probabilidad del empate (~20 %) y suman ~0,8.
- Si solo hay un lado, su escalera de líneas: la cuota europea de "A -1" (gana por 2 o
  más) es la de "A -1.5"; la asiática es (1 - P(gana por 1)) / P(gana por 2+), sacadas
  de -0.5 y -1.5. Medido el 2026-10-01 con 1.690 cuotas en vivo: 99,2 % asiáticas; los
  13 casos "europeos" eran todos cuotas >= 5,5 topadas por la casa (bet777 9,0 en -3 y
  -3.5), por eso solo se juzga con cuota de la línea difícil <= LADDER_MAX_ODDS.
"""

import math
import re

from .matching import event_key
from .models import Market

# Hándicap (de goles, córners, sets...; de partido o de periodo) con línea sin "/".
_AH_RE = re.compile(r"^(.*\bAH(?:_[A-Z0-9]+)*)_(-?\d+(?:\.\d+)?)$")
LADDER_MAX_ODDS = 5.0

ASIAN = "asiatico"
EUROPEAN = "europeo"
UNKNOWN = "sin_comprobar"


def whole_line(market_type: str) -> tuple[str, float] | None:
    """(prefijo, línea) si es un hándicap de línea entera ("AH_HT_-1" -> ("AH_HT", -1.0))."""
    match = _AH_RE.match(market_type.replace("+", ""))
    if not match or "AH" not in match.group(1).split("_"):
        return None
    line = float(match.group(2))
    return (match.group(1), line) if line == int(line) else None


def _ladders(groups: list[Market]) -> dict[tuple, dict[float, dict[str, float]]]:
    """(deporte, partido, prefijo, casa) -> {línea: {lado: mejor cuota}}, de todas las líneas."""
    ladders: dict[tuple, dict[float, dict[str, float]]] = {}
    for group in groups:
        match = _AH_RE.match(group.market_type.replace("+", ""))
        if not match or "AH" not in match.group(1).split("_"):
            continue
        line = float(match.group(2))
        for o in group.outcomes:
            key = (group.sport, event_key(group.event), match.group(1), o.bookmaker)
            sides = ladders.setdefault(key, {}).setdefault(line, {})
            sides[o.name] = max(sides.get(o.name, 0.0), o.odds)
    return ladders


def _ladder_verdict(lines: dict[float, dict[str, float]], line: float, side: str, odds: float) -> str:
    hard, easy = (line - 0.5, line + 0.5) if side == "1" else (line + 0.5, line - 0.5)
    hard_odds = lines.get(hard, {}).get(side)
    easy_odds = lines.get(easy, {}).get(side)
    if not hard_odds or not easy_odds or hard_odds > LADDER_MAX_ODDS:
        return UNKNOWN
    p_win, p_easy = 1 / hard_odds, 1 / easy_odds
    if p_easy <= p_win:
        return UNKNOWN
    asian = (1 - (p_easy - p_win)) / p_win
    if abs(math.log(odds / hard_odds)) < abs(math.log(odds / asian)):
        return EUROPEAN
    return ASIAN


def check_whole_handicaps(groups: list[Market]) -> tuple[list[Market], dict[int, dict[str, str]], int]:
    """Clasifica cada casa de cada hándicap de línea entera y QUITA las patas de las que
    se comportan como europeo (3 vías): esa cuota no vale para la surebet.

    Devuelve (grupos, {id(grupo): {casa: veredicto}}, nº de patas quitadas)."""
    ladders = _ladders(groups)
    verdicts: dict[int, dict[str, str]] = {}
    dropped = 0
    result: list[Market] = []
    for group in groups:
        parsed = whole_line(group.market_type)
        if parsed is None:
            result.append(group)
            continue
        prefix, line = parsed
        by_book: dict[str, str] = {}
        for book in {o.bookmaker for o in group.outcomes}:
            best: dict[str, float] = {}
            for o in group.outcomes:
                if o.bookmaker == book:
                    best[o.name] = max(best.get(o.name, 0.0), o.odds)
            if "1" in best and "2" in best:
                by_book[book] = ASIAN if 1 / best["1"] + 1 / best["2"] >= 1.0 else EUROPEAN
                continue
            lines = ladders.get((group.sport, event_key(group.event), prefix, book), {})
            side, odds = next(iter(best.items()))
            by_book[book] = _ladder_verdict(lines, line, side, odds)
        bad = {book for book, verdict in by_book.items() if verdict == EUROPEAN}
        if bad:
            kept = [o for o in group.outcomes if o.bookmaker not in bad]
            dropped += len(group.outcomes) - len(kept)
            group = Market(
                event=group.event,
                sport=group.sport,
                market_type=group.market_type,
                outcomes=kept,
                fetched_at=group.fetched_at,
                start_time=group.start_time,
            )
        verdicts[id(group)] = {book: v for book, v in by_book.items() if book not in bad}
        result.append(group)
    return result, verdicts, dropped
