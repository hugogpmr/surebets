"""Tipos de mercado que no se leen ni se cruzan.

Decidido con el usuario el 2026-10-03 a partir del backtest (1-3 oct) y del histórico de avisos
(desde el 27-sep): estos grupos no dieron NINGUNA surebet válida y eran un tercio del volumen que
no daba nada (VM al límite de CPU con el ciclo de 7 min):

- par/impar de todo (goles, córners, tarjetas, por mitad, cuarto, set o equipo): ~19.700 mercados de
  Altenar y ~700 de Kambi por ciclo, ~6.200 comparaciones;
- primer/último gol y primer/último córner: ~8.600 de Altenar, ~2.500 comparaciones.

No entran "primer tiro a puerta", "primer fuera de juego" ni "primera falta". Se quitan al leer las
fichas de Altenar y Kambi (memoria y caché de fichas) y en el escaneo para todas las casas (cruce).
`EXCLUDED_MARKETS` (expresión regular) cambia la lista; vacío = no se quita nada.
"""

import os
import re

DEFAULT_EXCLUDED = r"(?:^|_)OE(?:_|$)|^(?:FIRST|LAST)_GOAL(?:_|$)|^CORNERS_(?:FIRST|LAST)(?:_|$)"

_pattern = os.environ.get("EXCLUDED_MARKETS", DEFAULT_EXCLUDED)
_EXCLUDED = re.compile(_pattern) if _pattern else None


def is_excluded_market(market_type: str) -> bool:
    return _EXCLUDED is not None and _EXCLUDED.search(market_type) is not None


def keep_markets(markets: list) -> list:
    """Los mercados de `markets` cuyo tipo no está excluido."""
    if _EXCLUDED is None:
        return markets
    return [m for m in markets if not _EXCLUDED.search(m.market_type)]
