"""Tabla de alias de equipos para desambiguar el cruce de eventos entre
casas de apuestas.

Comparar nombres de equipo por similitud de texto genérica es insuficiente
para clubes españoles: "Barcelona" y "Celta" comparten suficientes letras en
común (ratio ~0.57) como para confundirse, y "Atlético Madrid" / "Real
Madrid" comparten literalmente la palabra "Madrid". Con una liga conocida y
acotada (20 equipos), una tabla de alias curada a mano es más fiable que
cualquier heurística de similitud.

Cada entrada es un conjunto de variantes normalizadas (ver `_normalize` en
matching.py: minúsculas, sin acentos, solo alfanumérico) tal como las emiten
los proveedores ya implementados (Sportium, Betfair, Winamax, Kirolbet).
Ampliar esta tabla al añadir más casas o más ligas.
"""

LALIGA_ALIASES: list[set[str]] = [
    {"atletico madrid", "atletico de madrid", "at madrid", "atl madrid", "atletico"},
    {"real madrid", "r madrid"},
    {"barcelona", "fc barcelona"},
    {"celta", "celta vigo", "celta de vigo"},
    {"racing santander", "racing s", "racing de santander", "r santander"},
    {"osasuna", "ca osasuna"},
    {"sevilla", "sevilla fc"},
    {"deportivo", "deportivo la coruna", "deportivo de a coruna", "rc deportivo"},
    {"levante", "levante ud"},
    {"athletic", "athletic bilbao", "athletic de bilbao", "ath bilbao", "athletic club"},
    {"real betis", "betis"},
    {"getafe", "getafe cf"},
    {"malaga", "malaga cf"},
    {"villarreal", "villarreal cf"},
    {"espanyol", "rcd espanyol"},
    {"elche", "elche cf"},
    {"rayo vallecano", "rayo v", "rayo"},
    {"alaves", "deportivo alaves"},
    {"valencia", "valencia cf"},
    {"real sociedad", "r sociedad"},
]


def canonical_team(normalized_name: str) -> str | None:
    """Devuelve un id canónico para un nombre de equipo ya normalizado, o
    None si no está en la tabla (equipo de otra liga/deporte aún no
    cubierto).
    """
    for group in LALIGA_ALIASES:
        if normalized_name in group:
            return next(iter(group))
    return None
