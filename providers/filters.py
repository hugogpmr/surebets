"""Filtros de partidos que no queremos escanear, comunes a Altenar y Kambi.

- Fútbol virtual / e-soccer (FIFA con nombres de jugador, "Esports Battle",
  "Cyber Live Arena"...): partidos simulados de 2x4-6 minutos que empiezan cada
  pocos minutos, no son pre-partido en ningún sentido útil y llegaron a ser el
  ~58 % de los partidos de Kambi (verificado el 2026-09-21).
- Fútbol femenino: partido real, pero cada plataforma lo nombra distinto
  ("Bayern Munich (F)", "FC Porto (W)") y los comparadores no lo traen, así que
  casi nunca cruza. Se puede volver a activar con EXCLUDE_WOMENS_FOOTBALL=0.

Se decide con las etiquetas que da la propia casa (categoría/competición/ruta y
nombres de equipo), no con el aspecto del nombre. Ojo: NO se filtra por la palabra
"FIFA" (hay torneos reales como la "FIFA ASEAN Cup").
"""

import os
import re

_ESPORTS = re.compile(r"e-?sports?|e-?battles?|cyber live|cla world cup|efootball|e-?soccer|virtual", re.IGNORECASE)
_WOMENS = re.compile(
    r"\((?:w|f)\)|\bfem\b|femen|feminin|femmin|femenil|mujeres|women|woman|frauen|vrouwen|kvinn|kobiet|dames|damallsvenskan",
    re.IGNORECASE,
)


def _flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() not in ("0", "false", "no", "")


def exclude_esports_default() -> bool:
    return _flag("EXCLUDE_ESPORTS")


def exclude_womens_default() -> bool:
    return _flag("EXCLUDE_WOMENS_FOOTBALL")


def is_esports(*labels: str | None) -> bool:
    return any(label and _ESPORTS.search(label) for label in labels)


def is_womens(*labels: str | None) -> bool:
    return any(label and _WOMENS.search(label) for label in labels)


def is_excluded(labels: list[str | None], exclude_esports: bool, exclude_women: bool) -> bool:
    """`labels` = categoría, competición, ruta y nombres de equipo del partido."""
    return (exclude_esports and is_esports(*labels)) or (exclude_women and is_womens(*labels))
