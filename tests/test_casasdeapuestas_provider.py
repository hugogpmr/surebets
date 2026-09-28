import base64
import time

import httpx

from providers.casasdeapuestas import (
    _split_period,
    discover_competitions,
    discover_events,
    parse_event_markets,
)


def odd(mercado, nombre, bookie, price, hidden=False):
    classes = "odd odd-h cuota_oculta" if hidden else "odd odd-h"
    return (
        f'<div class="{classes}" data-nombre="{nombre}" data-mercado="{mercado}">'
        f"<span>{price}</span>"
        f'<div class="bookie" data-bookie="{bookie}"></div>'
        "</div>"
    )


def page(home, away, odds_html, timestamp=1791572400):
    body = "".join(odds_html)
    return (
        f'<h1 id="h1_partido">Apuestas {home} - {away}</h1>'
        f'<time datetime="2026-10-09T21:00:00+02:00" data-date-utc="{timestamp}"></time>'
        f"{body}"
    )


def by_type(markets):
    return {m.market_type: m for m in markets}


def odds(market):
    return {o.name: o.odds for o in market.outcomes}


def test_split_period():
    assert _split_period("1X2 - Primera mitad") == ("1X2", "_HT")
    assert _split_period("Ganador - 1º Mitad") == ("Ganador", "_HT")
    assert _split_period("Total de goles - Segunda mitad") == ("Total de goles", "_2H")
    assert _split_period("Final del partido (1X2)") == ("Final del partido (1X2)", "")


def test_1x2_dc_btts_dnb_and_oe():
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Final del partido (1X2)", "Malaga", "bet365", "2.70"),
            odd("Final del partido (1X2)", "Empate", "codere", "3.40"),
            odd("Final del partido (1X2)", "Espanyol", "retabet", "2.72"),
            odd("Doble oportunidad", "Malaga o Empate", "bet365", "1.49"),
            odd("Doble oportunidad", "Espanyol o Empate", "888sport", "1.50"),
            odd("Doble oportunidad", "Malaga o Espanyol", "1xbet_es", "1.37"),
            odd("Ambos equipos marcan", "Sí", "bet365", "1.81"),
            odd("Ambos equipos marcan", "No", "codere", "2.00"),
            odd("Empate, apuesta no válida", "Malaga", "ijuego", "1.87"),
            odd("Empate, apuesta no válida", "Espanyol", "888sport", "1.95"),
            odd("Par/Impar", "Par", "bet365", "1.95"),
            odd("Par/Impar", "Impar", "codere", "1.85"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["1X2"]) == {"1": 2.70, "X": 3.40, "2": 2.72}
    assert odds(markets["DC"]) == {"1X": 1.49, "X2": 1.50, "12": 1.37}
    assert odds(markets["BTTS"]) == {"Yes": 1.81, "No": 2.00}
    assert odds(markets["DNB"]) == {"1": 1.87, "2": 1.95}
    assert odds(markets["OE"]) == {"Even": 1.95, "Odd": 1.85}
    assert all(o.bookmaker in ("bet365", "codere", "retabet", "888sport", "1xbet_es", "ijuego") for m in markets.values() for o in m.outcomes)


def test_winner_market_without_draw_is_ml_not_1x2():
    # Baloncesto/tenis: "Ganador" sin "Empate" -> ML, no 1X2.
    html = page(
        "Detroit Pistons",
        "Boston Celtics",
        [
            odd("Ganador", "Detroit Pistons", "bet365", "1.90"),
            odd("Ganador", "Boston Celtics", "codere", "1.85"),
        ],
    )
    markets = by_type(parse_event_markets(html, "baloncesto"))
    assert "1X2" not in markets
    assert odds(markets["ML"]) == {"1": 1.90, "2": 1.85}


def test_winner_market_with_draw_is_1x2_even_when_labelled_ganador():
    # Balonmano/NFL: "Ganador" SÍ trae "Empate" -> se emite como 1X2, no ML.
    html = page(
        "HC Erlangen",
        "ThSV Eisenach",
        [
            odd("Ganador", "HC Erlangen", "bet365", "1.40"),
            odd("Ganador", "Empate", "codere", "8.00"),
            odd("Ganador", "ThSV Eisenach", "retabet", "6.50"),
        ],
    )
    markets = by_type(parse_event_markets(html, "balonmano"))
    assert "ML" not in markets
    assert odds(markets["1X2"]) == {"1": 1.40, "X": 8.00, "2": 6.50}


def test_over_under_lines_group_by_line_and_half():
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Total de goles", "Más de 0.5", "retabet", "1.08"),
            odd("Total de goles", "Menos de 0.5", "interwetten", "11"),
            odd("Total de goles", "Más de 2.5", "bet365", "1.90"),
            odd("Total de goles", "Menos de 2.5", "codere", "1.90"),
            odd("Total de goles - Primera mitad", "Más de 0.5", "bet365", "1.43"),
            odd("Total de goles - Primera mitad", "Menos de 0.5", "retabet", "2.90"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["OU_0.5"]) == {"Over": 1.08, "Under": 11.0}
    assert odds(markets["OU_2.5"]) == {"Over": 1.90, "Under": 1.90}
    assert odds(markets["OU_HT_0.5"]) == {"Over": 1.43, "Under": 2.90}


def test_asian_handicap_normalizes_line_to_home_perspective():
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Hándicap Asiático", "Malaga -2.5", "1xbet_es", "12"),
            odd("Hándicap Asiático", "Espanyol +2.5", "jokerbet", "1.03"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["AH_-2.5"]) == {"1": 12.0, "2": 1.03}


def test_basketball_handicap_uses_generic_handicap_label():
    html = page(
        "Detroit Pistons",
        "Boston Celtics",
        [
            odd("Hándicap", "Detroit Pistons -4.5", "bet365", "1.90"),
            odd("Hándicap", "Boston Celtics +4.5", "codere", "1.90"),
        ],
    )
    markets = by_type(parse_event_markets(html, "baloncesto"))
    assert odds(markets["AH_-4.5"]) == {"1": 1.90, "2": 1.90}


def test_excluded_markets_are_never_emitted():
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Marcador correcto", "Malaga 1-0", "luckia", "8.60"),
            odd("Hándicap Europeo", "2 -1", "cgmapuestas", "5.00"),
            odd("Descanso/Final", "Malaga/Malaga", "bet365", "4.33"),
            odd("Gana a 0", "Y1", "interwetten", "4.40"),
            odd("¿Primer equipo en marcar?", "Malaga", "kirolbet", "2.02"),
        ],
    )
    markets = parse_event_markets(html, "futbol")
    assert markets == []


def test_hidden_cuota_oculta_cells_are_skipped():
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Ambos equipos marcan", "Sí", "bet365", "999", hidden=True),
            odd("Ambos equipos marcan", "No", "codere", "2.00"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["BTTS"]) == {"No": 2.00}


def test_start_time_extracted_as_utc():
    html = page("Malaga", "Espanyol", [odd("Ambos equipos marcan", "Sí", "bet365", "1.81")])
    from providers.casasdeapuestas import _extract_start_time

    start = _extract_start_time(html)
    assert start is not None
    assert start.year == 2026 and start.month == 10 and start.day == 9


def _mock_client(routes: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            return httpx.Response(200, text=routes[path])
        return httpx.Response(404, text="")

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://www.casasdeapuestas.com")


def test_discover_competitions_combines_visible_links_and_hidden_filter():
    league_id = base64.b64encode(b"/cuotas/futbol/italia/serie-b/").decode()
    html = (
        '<a href="/cuotas/futbol/espana/primera-division/">LaLiga</a>'
        f'<div data-league-id="{league_id}">Serie B</div>'
        '<a href="/cuotas/futbol/">Fútbol</a>'  # sin liga: no cuenta como competición
    )
    client = _mock_client({"/cuotas/futbol/": html})
    competitions = discover_competitions(client, "futbol")
    assert "/cuotas/futbol/espana/primera-division" in competitions
    assert "/cuotas/futbol/italia/serie-b" in competitions
    assert "/cuotas/futbol" in competitions  # la raíz se añade siempre, ver docstring


def test_discover_events_decodes_data_lnk():
    slug_b64 = base64.b64encode(b"/cuotas/evento/malaga-espanyol-540966/").decode()
    html = f'<div class="event-teams"><span data-lnk="{slug_b64}">Malaga<br>Espanyol</span></div>'
    client = _mock_client({"/cuotas/futbol/espana/primera-division/": html})
    events = discover_events(client, "/cuotas/futbol/espana/primera-division")
    assert events == ["/cuotas/evento/malaga-espanyol-540966"]


def test_cache_units_yields_one_callable_per_real_competition(monkeypatch):
    # Integración real de CasasDeApuestasProvider.cache_units (no el fake de
    # test_cache.py): confirma que la lista de competiciones -> lista de unidades es
    # correcta, y que invocar una unidad de verdad hace la petición esperada.
    from providers.casasdeapuestas import CasasDeApuestasProvider

    league_id = base64.b64encode(b"/cuotas/futbol/italia/serie-b/").decode()
    sport_index_html = f'<div data-league-id="{league_id}">Serie B</div>'
    slug_b64 = base64.b64encode(b"/cuotas/evento/juve-milan-1/").decode()
    competition_html = f'<div class="event-teams"><span data-lnk="{slug_b64}">Juve<br>Milan</span></div>'
    # timestamp cercano a "ahora" (no el fijo de 2026-10-09 que usa `page()` por
    # defecto): `_fetch_event` de verdad descarta partidos fuera de `horizon_hours`
    # (48h por defecto), a diferencia de `parse_event_markets`, que no filtra por fecha.
    soon = int(time.time()) + 3600
    event_html = page("Juve", "Milan", [odd("Ambos equipos marcan", "Sí", "bet365", "1.81")], timestamp=soon)

    routes = {
        "/cuotas/futbol/": sport_index_html,
        "/cuotas/futbol/italia/serie-b/": competition_html,
        "/cuotas/evento/juve-milan-1/": event_html,
    }

    real_client = httpx.Client  # `_mock_client` debe seguir usando el Client real, no el parcheado

    def fake_client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            return httpx.Response(200, text=routes[path]) if path in routes else httpx.Response(404, text="")

        return real_client(transport=httpx.MockTransport(handler), base_url="https://www.casasdeapuestas.com")

    monkeypatch.setattr("providers.casasdeapuestas.httpx.Client", fake_client_factory)

    provider = CasasDeApuestasProvider()
    units = provider.cache_units(["futbol_champions"])
    keys = {key for key, _ in units}
    assert "/cuotas/futbol" in {k.split("::", 1)[1] for k in keys}  # la raíz siempre se incluye
    assert "/cuotas/futbol/italia/serie-b" in {k.split("::", 1)[1] for k in keys}

    fetch_serie_b = next(fn for key, fn in units if key == "futbol::/cuotas/futbol/italia/serie-b")
    markets = fetch_serie_b()
    assert len(markets) == 1 and markets[0].event == "Juve vs. Milan"


def test_baseball_key_resolves_to_the_beisbol_section(monkeypatch):
    # "beisbol_mlb" (clave de SPORTS en scripts/scan_once_action.py) debe colapsar a
    # "beisbol" y descubrir esa sección - añadido 2026-09-28: SPORTS ya la pedía desde la
    # retirada de CuotasAhoraProvider, pero SPORT_SECTIONS no tenía la clave y se ignoraba
    # en silencio (ver el comentario de esa retirada en scripts/scan_once_action.py).
    from providers.casasdeapuestas import SPORT_SECTIONS, CasasDeApuestasProvider

    assert SPORT_SECTIONS["beisbol"] == "beisbol"

    league_id = base64.b64encode(b"/cuotas/beisbol/estados-unidos/mlb/").decode()
    sport_index_html = f'<div data-league-id="{league_id}">MLB</div>'
    real_client = httpx.Client  # ver el comentario equivalente en el test de arriba

    def fake_client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=sport_index_html) if request.url.path == "/cuotas/beisbol/" else httpx.Response(404, text="")

        return real_client(transport=httpx.MockTransport(handler), base_url="https://www.casasdeapuestas.com")

    monkeypatch.setattr("providers.casasdeapuestas.httpx.Client", fake_client_factory)

    units = CasasDeApuestasProvider().cache_units(["beisbol_mlb"])
    keys = {key.split("::", 1)[1] for key, _ in units}
    assert "/cuotas/beisbol/estados-unidos/mlb" in keys


def test_bookmaker_names_that_differ_from_the_direct_providers_are_normalized():
    # Confirmado en vivo el 2026-09-28 contra la caché real de la VM: el sitio identifica
    # estas dos casas con un data-bookie distinto del `name` que usa su proveedor directo
    # (providers/williamhill.py, providers/marcaapuestas.py) - sin normalizar, el motor las
    # trataría como dos casas distintas y podría fabricar una "surebet" entre ellas.
    html = page(
        "Real Madrid", "Sevilla",
        [
            odd("Final del partido (1X2)", "Real Madrid", "william_hill", "2.10"),
            odd("Final del partido (1X2)", "Empate", "william_hill", "3.40"),
            odd("Final del partido (1X2)", "Sevilla", "marca_apuestas", "2.72"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    bookmakers = {o.bookmaker for o in markets["1X2"].outcomes}
    assert bookmakers == {"williamhill", "marcaapuestas"}
    assert "william_hill" not in bookmakers and "marca_apuestas" not in bookmakers


def test_bookmaker_names_that_already_match_are_left_untouched():
    html = page(
        "Real Madrid", "Sevilla",
        [
            odd("Final del partido (1X2)", "Real Madrid", "betfair", "2.10"),
            odd("Final del partido (1X2)", "Empate", "betfair", "3.40"),
            odd("Final del partido (1X2)", "Sevilla", "bwin", "2.72"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert {o.bookmaker for o in markets["1X2"].outcomes} == {"betfair", "bwin"}
