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
            odd("Empate, apuesta no válida", "Malaga", "luckia", "1.87"),
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
    assert all(o.bookmaker in ("bet365", "codere", "retabet", "888sport", "1xbet_es", "luckia") for m in markets.values() for o in m.outcomes)


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


def test_three_way_integer_handicap_of_888sport_and_betfair_is_not_emitted():
    # Gales-Noruega, 1ª parte (2026-09-30): "Gales +1" de 888sport (1,75) contra "Noruega -1" de
    # Betfair (4,33) era un falso 20 %: su hándicap de líneas enteras es de 3 vías y no cubre
    # "Noruega gana por 1". Con esas dos casas no debe salir ningún mercado de línea entera.
    html = page(
        "Gales",
        "Noruega",
        [
            odd("Hándicap Asiático - Primera mitad", "Gales +1.0", "888sport", "1.75"),
            odd("Hándicap Asiático - Primera mitad", "Noruega -1", "betfair", "4.33"),
            odd("Hándicap Asiático - Primera mitad", "Gales -1.0", "888sport", "6.0"),
            odd("Hándicap Asiático - Primera mitad", "Noruega +1", "betfair", "1.5"),
        ],
    )
    assert parse_event_markets(html, "futbol") == []


def test_three_way_bookies_keep_half_point_lines_and_do_not_affect_other_bookies():
    html = page(
        "Gales",
        "Noruega",
        [
            odd("Hándicap Asiático - Primera mitad", "Gales +1.0", "888sport", "1.75"),  # 3 vías: fuera
            odd("Hándicap Asiático - Primera mitad", "Noruega -1", "interwetten", "2.10"),
            odd("Hándicap Asiático - Primera mitad", "Gales +1", "interwetten", "1.72"),  # 2 vías real: se queda
            odd("Hándicap", "Gales +4.5", "betfair", "1.90"),  # línea de medio punto: siempre 2 vías
            odd("Hándicap", "Noruega -4.5", "codere", "1.95"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["AH_HT_1"]) == {"1": 1.72, "2": 2.10}
    assert markets["AH_HT_1"].outcomes[0].bookmaker == "interwetten"
    assert {o.bookmaker for o in markets["AH_4.5"].outcomes} == {"betfair", "codere"}


def test_handicap_pair_of_one_bookie_summing_under_one_is_dropped():
    # Un 2 vías real suma >1 (margen de la casa): si las dos patas de UNA casa en la misma
    # línea suman menos, es un mercado mezclado y no puede cruzar con nadie.
    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Hándicap Asiático", "Malaga -1", "casaX", "3.00"),
            odd("Hándicap Asiático", "Espanyol +1", "casaX", "1.40"),  # 1/3 + 1/1.4 = 1.05: sana
            odd("Hándicap Asiático", "Malaga -2", "casaY", "5.00"),
            odd("Hándicap Asiático", "Espanyol +2", "casaY", "1.10"),  # 1/5 + 1/1.1 = 1.11: sana
            odd("Hándicap Asiático", "Malaga +1.5", "casaZ", "1.80"),
            odd("Hándicap Asiático", "Espanyol -1.5", "casaZ", "4.00"),  # 1/1.8 + 1/4 = 0.81: mezclada
            odd("Hándicap Asiático", "Espanyol -1.5", "casaW", "2.50"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert odds(markets["AH_-1"]) == {"1": 3.0, "2": 1.4}
    assert odds(markets["AH_-2"]) == {"1": 5.0, "2": 1.1}
    # casaZ fuera (sus dos patas sumaban 0,81); queda solo la pata de casaW
    assert {o.bookmaker for o in markets["AH_1.5"].outcomes} == {"casaW"}


def test_sanitize_cached_market_cleans_old_bad_reads():
    from engine.models import Market, Outcome
    from providers.casasdeapuestas import sanitize_cached_market

    def market(market_type, *legs):
        return Market(
            event="Gales vs. Noruega",
            sport="futbol",
            market_type=market_type,
            outcomes=[Outcome(name=n, bookmaker=b, odds=p, source="casasdeapuestas") for n, b, p in legs],
        )

    bad = market("AH_HT_1", ("1", "888sport", 1.75), ("2", "betfair", 4.33))
    assert sanitize_cached_market(bad) is None
    mixed = market("AH_HT_1", ("1", "888sport", 1.75), ("2", "betfair", 4.33), ("1", "interwetten", 1.72), ("2", "interwetten", 2.1))
    cleaned = sanitize_cached_market(mixed)
    assert {o.bookmaker for o in cleaned.outcomes} == {"interwetten"}
    half = market("AH_4.5", ("1", "betfair", 1.9), ("2", "codere", 1.95))
    assert sanitize_cached_market(half) is half
    other = market("OU_2.5", ("Over", "888sport", 1.9), ("Under", "bet365", 1.9))
    assert sanitize_cached_market(other) is other


def test_betfair_handicap_is_dropped_in_nfl_and_basketball_but_kept_in_tennis():
    # La escalera de Betfair llega con los equipos intercambiados en esos deportes (ver
    # _SWAPPED_SIDES): no puede cruzarse con las demás casas.
    odds_html = [
        odd("Hándicap", "Malaga -1.5", "1xbet_es", "2.36"),
        odd("Hándicap", "Espanyol +1.5", "betfair", "2.05"),
    ]
    for sport in ("americano", "baloncesto"):
        markets = by_type(parse_event_markets(page("Malaga", "Espanyol", odds_html), sport))
        assert {o.bookmaker for o in markets["AH_-1.5"].outcomes} == {"1xbet_es"}
    tennis = by_type(parse_event_markets(page("Malaga", "Espanyol", [odd("Hándicap de juegos", n, b, p) for _, n, b, p in
        [(0, "Malaga -1.5", "1xbet_es", "2.36"), (0, "Espanyol +1.5", "betfair", "1.6")]]), "tenis"))
    assert {o.bookmaker for o in tennis["AH_-1.5"].outcomes} == {"1xbet_es", "betfair"}


def test_tennis_sets_handicap_labelled_as_games_is_dropped(monkeypatch):
    from providers import casasdeapuestas

    monkeypatch.setattr(casasdeapuestas, "EXCLUDED_BOOKIES", frozenset())  # probar la regla, no la exclusión
    # Goldenpark/Olybet publican el hándicap de SETS ±1.5 como "de juegos" (1-oct-2026: falsas del
    # 18-23 % en Alcaraz-Michelsen). Sus ±1.5 se descartan; los de las demás casas y sus otras
    # líneas no.
    html = page(
        "Jaume Munar",
        "Jaime Faria",
        [
            odd("Hándicap de juegos", "Jaume Munar -1.5", "goldenpark", "2.27"),
            odd("Hándicap de juegos", "Jaime Faria +1.5", "goldenpark", "4.0"),
            odd("Hándicap de juegos", "Jaime Faria +1.5", "olybet", "8.25"),
            odd("Hándicap de juegos", "Jaume Munar -1.5", "bet365", "1.83"),
            odd("Hándicap de juegos", "Jaime Faria +1.5", "casumo", "1.95"),
            odd("Hándicap de juegos", "Jaume Munar -3.5", "goldenpark", "2.4"),
        ],
    )
    markets = by_type(parse_event_markets(html, "tenis"))
    assert {o.bookmaker for o in markets["AH_-1.5"].outcomes} == {"bet365", "casumo"}
    assert {o.bookmaker for o in markets["AH_-3.5"].outcomes} == {"goldenpark"}


def test_sanitize_cached_market_drops_tennis_sets_as_games(monkeypatch):
    from engine.models import Market, Outcome
    from providers import casasdeapuestas

    monkeypatch.setattr(casasdeapuestas, "EXCLUDED_BOOKIES", frozenset())
    from providers.casasdeapuestas import sanitize_cached_market

    bad = Market(
        event="Carlos Alcaraz vs. Alex Michelsen",
        sport="tenis",
        market_type="AH_-1.5",
        outcomes=[
            Outcome(name="1", bookmaker="goldenpark", odds=1.45, source="casasdeapuestas"),
            Outcome(name="2", bookmaker="olybet", odds=8.25, source="casasdeapuestas"),
        ],
    )
    assert sanitize_cached_market(bad) is None


def _ladder(home, away, bookie, pairs):
    """pairs = [(línea del local, cuota del local, cuota del visitante)] de una casa."""
    html = []
    for line, home_odds, away_odds in pairs:
        html.append(odd("Hándicap", f"{home} {line:+g}", bookie, str(home_odds)))
        html.append(odd("Hándicap", f"{away} {-line:+g}", bookie, str(away_odds)))
    return html


def test_bookmaker_whose_handicap_ladder_fits_the_swapped_teams_is_dropped():
    lines = [-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5]
    # prob. de que cubra el local en cada línea (sube con la línea; local NO favorito, así que
    # intercambiar equipos cambia la escalera). Cada casa aplica su margen (cuotas x 0,95).
    truth = dict(zip(lines, [0.12, 0.18, 0.25, 0.33, 0.43, 0.52, 0.61, 0.69]))

    def honest(bookie):
        return _ladder("Malaga", "Espanyol", bookie, [(L, round(0.95 / truth[L], 2), round(0.95 / (1 - truth[L]), 2)) for L in lines])

    # casa invertida: declara el mismo mercado con los equipos cambiados (su "local" es en realidad el visitante)
    swapped = _ladder("Malaga", "Espanyol", "casaInv", [(L, round(0.95 / (1 - truth[-L]), 2), round(0.95 / truth[-L], 2)) for L in lines])
    markets = parse_event_markets(page("Malaga", "Espanyol", honest("casaA") + honest("casaB") + swapped), "futbol")
    books = {o.bookmaker for m in markets for o in m.outcomes}
    assert "casaInv" not in books and {"casaA", "casaB"} <= books


def test_honest_ladders_are_not_dropped_as_inverted():
    lines = [-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5]
    truth = dict(zip(lines, [0.12, 0.18, 0.25, 0.33, 0.43, 0.52, 0.61, 0.69]))
    html = page("Malaga", "Espanyol", sum((_ladder("Malaga", "Espanyol", b, [(L, round(1 / truth[L] * f, 2), round(1 / (1 - truth[L]) * f, 2)) for L in lines]) for b, f in (("casaA", 0.96), ("casaB", 0.94), ("casaC", 0.97))), []))
    books = {o.bookmaker for m in parse_event_markets(html, "futbol") for o in m.outcomes}
    assert books == {"casaA", "casaB", "casaC"}


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


def test_excluded_and_aliased_bookies():
    from engine.models import Market, Outcome
    from providers import casasdeapuestas
    from providers.casasdeapuestas import sanitize_cached_market

    html = page(
        "Malaga",
        "Espanyol",
        [
            odd("Final del partido (1X2)", "Malaga", "betfair_exchange", "2.10"),
            odd("Final del partido (1X2)", "Empate", "daznbet_es", "3.40"),
            odd("Final del partido (1X2)", "Espanyol", "bet365", "3.90"),
        ],
    )
    markets = parse_event_markets(html, "futbol")
    assert {o.bookmaker for m in markets for o in m.outcomes} == {"daznbet", "bet365"}
    cached = Market(
        event="Malaga vs. Espanyol",
        sport="futbol",
        market_type="OU_2.5",
        outcomes=[
            Outcome(name="Over", bookmaker="betfair_exchange", odds=2.1, source="casasdeapuestas"),
            Outcome(name="Under", bookmaker="daznbet_es", odds=1.9, source="casasdeapuestas"),
        ],
    )
    cleaned = sanitize_cached_market(cached)
    assert [(o.name, o.bookmaker) for o in cleaned.outcomes] == [("Under", "daznbet")]
    assert casasdeapuestas.EXCLUDED_BOOKIES >= {"betfair_exchange"}


def test_football_winner_without_draw_is_still_1x2_never_ml():
    # Frosinone-Benevento (2026-10-02): el sitio daba "Final del partido (1X2)" sin "Empate". Como
    # ML cruzaba 1 contra 2 y salían falsas surebets del 14-25 % (sin cubrir el empate).
    html = page(
        "Frosinone",
        "Benevento",
        [
            odd("Final del partido (1X2)", "Frosinone", "jokerbet", "1.80"),
            odd("Final del partido (1X2)", "Benevento", "cgmapuestas", "3.60"),
        ],
    )
    markets = by_type(parse_event_markets(html, "futbol"))
    assert "ML" not in markets
    assert odds(markets["1X2"]) == {"1": 1.80, "2": 3.60}  # incompleto: el control de calidad lo descarta si nadie da el X
    plain_winner = by_type(parse_event_markets(page("A", "B", [odd("Ganador", "A", "x", "1.5"), odd("Ganador", "B", "y", "2.9")]), "futbol"))
    assert "ML" not in plain_winner


def test_sanitize_drops_old_football_ml_from_cache():
    from engine.models import Market, Outcome
    from providers.casasdeapuestas import sanitize_cached_market

    old = Market(event="Frosinone vs. Benevento", sport="futbol", market_type="ML",
                 outcomes=[Outcome("1", "jokerbet", 1.8), Outcome("2", "cgmapuestas", 3.6)])
    assert sanitize_cached_market(old) is None
    tennis = Market(event="A vs. B", sport="tenis", market_type="ML", outcomes=[Outcome("1", "bet365", 1.8), Outcome("2", "1xbet_es", 2.1)])
    assert sanitize_cached_market(tennis) is tennis
