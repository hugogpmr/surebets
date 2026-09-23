"""Traducción a castellano legible de los códigos internos de mercado
(`BTTS_HT`, `CORNERS_OU_HOME_2H_2.5`, `AH_-0.5/-1`...) y de sus resultados
(`1`, `X`, `Yes`, `Over`...) para los avisos de Telegram.

Los `market_type` los generan los proveedores con la forma
`[MÉTRICA_]BASE[_LOCAL|_VISITANTE][_HT|_2H][_LÍNEA]` (ver providers/altenar.py);
aquí solo se lee esa forma, no se toca el cálculo. Si un código no se
reconoce, se devuelve tal cual: un aviso feo es mejor que un aviso perdido.
"""

import re
from datetime import datetime, timezone

SPORT_NAMES = {
    "futbol": "Fútbol",
    "baloncesto": "Baloncesto",
    "tenis": "Tenis",
    "balonmano": "Balonmano",
    "beisbol": "Béisbol",
    "americano": "Fútbol americano",
}

# Qué se cuenta en los mercados de más/menos y hándicap según el deporte.
_SPORT_UNIT = {
    "futbol": "goles",
    "balonmano": "goles",
    "baloncesto": "puntos",
    "americano": "puntos",
    "tenis": "juegos",
    "beisbol": "carreras",
}

_METRIC_NOUNS = {
    "CORNERS": "córners",
    "CARDS": "tarjetas",
    "SOT": "tiros a puerta",
    "SHOTS": "tiros",
    "OFFSIDES": "fueras de juego",
    "FOULS": "faltas",
}
# "Primer/último X" de cada métrica (femenino/masculino según el sustantivo).
_METRIC_FIRST = {"CORNERS": ("Primer córner", "Último córner")}

_PERIODS = {"HT": "1ª parte", "2H": "2ª parte"}

# Mercados de sí/no: base -> frase con {team} (equipo al que se refiere).
_YES_NO_TITLES = {
    "BTTS": "Ambos equipos marcan",
    "CS": "{team} mantiene la portería a cero",
    "WTN": "{team} gana sin encajar gol",
    "WIN_BOTH_HALVES": "{team} gana las dos partes",
    "WIN_ANY_HALF": "{team} gana alguna de las partes",
    "SCORE_BOTH_HALVES": "{team} marca en las dos partes",
    "PENALTY": "Hay penalti en el partido",
}

# Primer/último evento (1 / Ninguno / 2): base -> texto del mercado.
_FIRST_EVENT_TITLES = {
    "FIRST_GOAL": "Primer gol",
    "LAST_GOAL": "Último gol",
    "FIRST_FOUL": "Primera falta",
    "FIRST_OFFSIDE": "Primer fuera de juego",
    "FIRST_SHOT_ON_TARGET": "Primer tiro a puerta",
}

_LINE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:/[+-]?\d+(?:\.\d+)?)?$")


def sport_name(sport: str) -> str:
    return SPORT_NAMES.get(sport, sport.capitalize())


def kickoff_line(start_time: datetime | None) -> str:
    """Línea del aviso con día y hora de inicio (hora de Madrid) y cuánto falta,
    p.ej. "🕐 Empieza 22/09 21:00 (en 3.5 h)". Si la fuente no informa la hora
    (los comparadores no la dan) lo dice, en vez de dejar la línea fuera."""
    if start_time is None:
        return "🕐 Fecha y hora del partido no disponibles"
    try:
        from zoneinfo import ZoneInfo

        local = start_time.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception:  # sin base de datos de zonas horarias (Windows sin tzdata)
        local = start_time.astimezone(timezone.utc)
    seconds = (start_time - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return f"🕐 Empezó {local:%d/%m %H:%M}"
    when = f"en {seconds / 3600:.1f} h" if seconds >= 3600 else f"en {int(seconds // 60)} min"
    return f"🕐 Empieza {local:%d/%m %H:%M} ({when})"


def split_teams(event: str) -> tuple[str, str]:
    """(local, visitante) de "A vs. B" / "A - B"; ("Local", "Visitante") si no se puede."""
    parts = re.split(r" vs\.? | - ", event, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return "Local", "Visitante"


def _signed(part: str) -> str:
    return part if part[0] in "+-" or part == "0" else f"+{part}"


def _flip(part: str) -> str:
    if part == "0":
        return "0"
    return ("+" if part[0] == "-" else "-") + part[1:]


def _handicap_lines(line: str) -> tuple[str, str]:
    """Línea del local y del visitante ("-0.5/-1" -> ("-0.5/-1", "+0.5/+1"))."""
    home = [_signed(p) for p in line.split("/")]
    return "/".join(home), "/".join(_flip(p) for p in home)


def _parse(market_type: str) -> dict:
    tokens = market_type.split("_")
    line = tokens.pop() if len(tokens) > 1 and _LINE_RE.match(tokens[-1]) else None
    period = next((t for t in tokens if t in _PERIODS), None)
    side = next((t for t in tokens if t in ("HOME", "AWAY")), None)
    rest = [t for t in tokens if t not in _PERIODS and t not in ("HOME", "AWAY")]
    metric = rest.pop(0) if len(rest) > 1 and rest[0] in _METRIC_NOUNS else None
    return {"base": "_".join(rest), "metric": metric, "side": side, "period": period, "line": line}


def market_title(market_type: str, event: str, sport: str) -> str:
    """Nombre del mercado en castellano, p.ej. "Ambos equipos marcan · 1ª parte"."""
    p = _parse(market_type)
    home, away = split_teams(event)
    base, metric, side, line = p["base"], p["metric"], p["side"], p["line"]
    team = {"HOME": home, "AWAY": away}.get(side, "")
    noun = _METRIC_NOUNS.get(metric) or _SPORT_UNIT.get(sport, "")
    of_team = f" de {team}" if team else ""

    if base in _YES_NO_TITLES:
        title = _YES_NO_TITLES[base].format(team=team or "el equipo")
    elif base in _FIRST_EVENT_TITLES or (metric and base in ("FIRST", "LAST")):
        if metric in _METRIC_FIRST:
            title = _METRIC_FIRST[metric][0 if base == "FIRST" else 1]
        else:
            title = _FIRST_EVENT_TITLES.get(base, market_type)
    elif base == "1X2":
        title = f"Más {noun}" if metric else "Resultado (1X2)"
    elif base == "DNB":
        title = "Empate no apuesta (si empatan, devuelven)"
    elif base == "DC":
        title = "Doble oportunidad"
    elif base == "OE":
        title = f"Total de {noun}{of_team}: impar o par"
    elif base == "OU" and line:
        title = f"Total de {noun}{of_team}: más o menos de {line}"
    elif base == "AH" and line:
        title = f"Hándicap asiático de {noun}" if metric else "Hándicap asiático"
    elif base == "EH" and line:
        title = f"Hándicap europeo ({home} {_handicap_lines(line)[0]})"
    else:
        return market_type
    if p["period"]:
        title += f" · {_PERIODS[p['period']]}"
    return title


def outcome_label(market_type: str, outcome: str, event: str, sport: str) -> str:
    """Qué se apuesta en un resultado, en castellano, p.ej. "Más de 9.5"."""
    p = _parse(market_type)
    home, away = split_teams(event)
    base, line = p["base"], p["line"]

    if outcome in ("Yes", "No"):
        return "Sí" if outcome == "Yes" else "No"
    if outcome in ("Odd", "Even"):
        return "Impar" if outcome == "Odd" else "Par"
    if outcome in ("Over", "Under") and line:
        return f"{'Más' if outcome == 'Over' else 'Menos'} de {line}"
    if outcome == "None":
        return "Ninguno"
    if base in ("AH", "EH") and line and outcome in ("1", "2"):
        home_line, away_line = _handicap_lines(line)
        return f"{home} {home_line}" if outcome == "1" else f"{away} {away_line}"
    if base == "DC":
        return {"1X": f"{home} o empate", "12": f"{home} o {away}", "X2": f"Empate o {away}"}.get(outcome, outcome)
    if outcome == "1":
        return home
    if outcome == "2":
        return away
    if outcome == "X":
        return "Empate"
    return outcome
