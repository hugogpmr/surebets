import asyncio
import logging
import re
import urllib.parse

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

logger = logging.getLogger(__name__)

DEFAULT_LEAGUE_URLS = {
    "futbol": "https://www.cuotasahora.com/football/spain/laliga-ea-sports/",
    "futbol_champions": "https://www.cuotasahora.com/football/europe/champions-league/",
    # Top 5 ligas europeas + Copa del Rey + LaLiga2 (verificado en vivo
    # 2026-09-16: URL de cada liga confirmada navegando cuotasahora.com).
    "futbol_premier": "https://www.cuotasahora.com/football/england/premier-league/",
    "futbol_seriea": "https://www.cuotasahora.com/football/italy/serie-a/",
    "futbol_bundesliga": "https://www.cuotasahora.com/football/germany/bundesliga/",
    "futbol_ligue1": "https://www.cuotasahora.com/football/france/ligue-1/",
    "futbol_europa_league": "https://www.cuotasahora.com/football/europe/europa-league/",
    # LaLiga2 se llama "LaLiga Hypermotion" desde el patrocinio actual.
    "futbol_laliga2": "https://www.cuotasahora.com/football/spain/laliga-hypermotion/",
    "futbol_copa_rey": "https://www.cuotasahora.com/football/spain/copa-del-rey/",
    # Segunda tanda de ligas de fútbol (verificado en vivo 2026-09-17: URL y
    # partidos reales confirmados navegando cuotasahora.com para las 4).
    "futbol_eredivisie": "https://www.cuotasahora.com/football/netherlands/eredivisie/",
    "futbol_liga_portugal": "https://www.cuotasahora.com/football/portugal/liga-portugal/",
    "futbol_championship": "https://www.cuotasahora.com/football/england/championship/",
    "futbol_mls": "https://www.cuotasahora.com/football/usa/mls/",
    # Tercera tanda (verificado en vivo 2026-09-17).
    "futbol_super_lig": "https://www.cuotasahora.com/football/turkey/super-lig/",
    "futbol_jupiler": "https://www.cuotasahora.com/football/belgium/jupiler-pro-league/",
    # Cuarta tanda (verificado en vivo 2026-09-17): ligas sudamericanas y
    # norteamericanas de peso, más Escocia. Saudi Pro League se comprobó
    # también pero sin próximos partidos anunciados en ese momento (liga
    # entre jornadas) - no se añade por ahora, no es un problema de URL.
    "futbol_brasileirao": "https://www.cuotasahora.com/football/brazil/serie-a-betano/",
    "futbol_liga_mx": "https://www.cuotasahora.com/football/mexico/liga-mx/",
    "futbol_liga_argentina": "https://www.cuotasahora.com/football/argentina/liga-profesional/",
    "futbol_scotland": "https://www.cuotasahora.com/football/scotland/premiership/",
    # Quinta tanda (verificado en vivo 2026-09-17): competiciones continentales
    # que faltaban (además de Champions/Europa League ya cubiertas) más los
    # dos torneos de clubes sudamericanos. Saudi Pro League se volvió a
    # comprobar en esta ronda y sigue sin próximos partidos anunciados - sigue
    # fuera por el mismo motivo que la tanda anterior.
    "futbol_conference_league": "https://www.cuotasahora.com/football/europe/conference-league/",
    "futbol_libertadores": "https://www.cuotasahora.com/football/south-america/copa-libertadores/",
    "futbol_sudamericana": "https://www.cuotasahora.com/football/south-america/copa-sudamericana/",
    # Sexta tanda (verificado en vivo 2026-09-17): ligas domésticas europeas de
    # menor tamaño pero con casas DGOJ activas. Grecia (Super League/
    # Super League 1) probada con dos slugs distintos, ambos 404 - no se
    # insistió más, queda pendiente encontrar el slug correcto.
    "futbol_austria": "https://www.cuotasahora.com/football/austria/bundesliga/",
    "futbol_suiza": "https://www.cuotasahora.com/football/switzerland/super-league/",
    "futbol_dinamarca": "https://www.cuotasahora.com/football/denmark/superliga/",
    "futbol_polonia": "https://www.cuotasahora.com/football/poland/ekstraklasa/",
    "futbol_noruega": "https://www.cuotasahora.com/football/norway/eliteserien/",
    # Séptima tanda (verificado en vivo 2026-09-17): más ligas domésticas
    # europeas. Rugby se volvió a comprobar en esta ronda (tercera vez) y
    # sigue sin partidos programados - se deja fuera otra vez.
    "futbol_suecia": "https://www.cuotasahora.com/football/sweden/allsvenskan/",
    "futbol_croacia": "https://www.cuotasahora.com/football/croatia/hnl/",
    # El slug de URL sigue siendo "fortuna-liga" aunque el sitio ya muestra el
    # nombre actual de la competición ("Chance Liga", tras cambio de
    # patrocinador) en el título de la página.
    "futbol_chequia": "https://www.cuotasahora.com/football/czech-republic/fortuna-liga/",
    # Baloncesto: mismo motor tipo Oddsportal que fútbol, verificado en vivo
    # contra un partido NBA real (misma tabla Bookmakers/1/2/Payout).
    "baloncesto_acb": "https://www.cuotasahora.com/basketball/spain/liga-endesa/",
    "baloncesto_euroleague": "https://www.cuotasahora.com/basketball/europe/euroleague/",
    "baloncesto_nba": "https://www.cuotasahora.com/basketball/usa/nba/",
    "baloncesto_eurocup": "https://www.cuotasahora.com/basketball/europe/eurocup/",
    # Tenis: a diferencia de fútbol/baloncesto no hay una URL de "liga"
    # estable (los torneos ATP/WTA rotan cada semana), así que se apunta
    # directamente al hub general de tenis, que lista los partidos del día
    # de todos los torneos activos con el mismo patrón "/tennis/h2h/...".
    "tenis_atp": "https://www.cuotasahora.com/tennis/",
    # Balonmano (deporte nuevo, verificado en vivo 2026-09-17): mismo motor y
    # misma familia de pestañas de mercado que fútbol (1X2 con empate, DC,
    # DNB/OE/Descanso-Final detrás de "Más", Más/Menos de + hándicap
    # asiático/europeo en acordeón) salvo "Ambos equipos marcan" (BTTS), que
    # no aparece como pestaña - no rompe nada, simplemente no se genera ese
    # market_type para este deporte (fallo silencioso ya contemplado en
    # _switch_market_tab). Se usa la Champions League masculina de EHF en vez
    # de una liga doméstica: mejor cobertura de casas (12 en la prueba en
    # vivo) que cualquier liga nacional de balonmano.
    "balonmano_champions": "https://www.cuotasahora.com/handball/europe/liga-de-campeones-masculina/",
    # Béisbol (deporte nuevo, verificado en vivo 2026-09-17): tabla por
    # defecto trae solo "1"/"2" (sin empate, igual que baloncesto - ya
    # contemplado por _parse_match). Mismas pestañas Más/Menos de/Hándicap
    # asiático/Hándicap europeo con la misma estructura de acordeón; no hay
    # "Ambos equipos marcan"/"Doble oportunidad" (no aplican sin empate
    # posible), igual que baloncesto.
    "beisbol_mlb": "https://www.cuotasahora.com/baseball/usa/mlb/",
    # Fútbol americano (deporte nuevo, verificado en vivo 2026-09-17): NFL.
    # Clave "americano_nfl" (no "futbol_americano_nfl") a propósito: el
    # deporte real se deriva con `sport_key.split("_", 1)[0]` (ver
    # _fetch_markets_async), así que un prefijo "futbol_" aquí lo fusionaría
    # por error con el fútbol normal en el motor de arbitraje. Igual que
    # baloncesto/béisbol, tabla por defecto sin empate ("1"/"2"). A
    # diferencia de baloncesto/béisbol, sí tiene "Ambos equipos marcan"
    # (BTTS) como pestaña directa - se extrae igual, sin caso especial.
    "americano_nfl": "https://www.cuotasahora.com/american-football/usa/nfl/",
}

# Segmento de URL que usa cuotasahora.com para cada deporte (difiere del
# nombre en español que usamos como clave de `sports`/`league_urls`), usado
# para construir el selector de enlaces a partidos ("/<segmento>/h2h/...").
SPORT_URL_SEGMENT = {
    "futbol": "football",
    "baloncesto": "basketball",
    "tenis": "tennis",
    "balonmano": "handball",
    "beisbol": "baseball",
    "americano": "american-football",
}

# Casas que devuelve CuotasAhora (comparador, no una casa en sí) y que
# tratamos como fuente para arbitraje. Verificado a mano el 2026-09-16 contra
# el buscador oficial de la DGOJ (ordenacionjuego.es/operadores-juego/
# operadores-licencia/operadores, las 78 fichas de operadores con licencia,
# una por una): TODAS las casas de esta lista tienen licencia vigente en
# España, incluido 1xBet.es (WAGERFAIR, S.A. — pese a la sospecha inicial de
# que fuera un operador offshore sin licencia, sí la tiene). Esta
# verificación es una foto de un momento dado: la DGOJ actualiza el registro
# mensualmente, así que puede quedar desfasada — revisar de nuevo en
# ordenacionjuego.es antes de operar con dinero real si ha pasado tiempo.
#
# Sportium/Betfair/Winamax se excluyen aquí a propósito aunque aparezcan en
# la tabla: ya los scrapeamos en directo (providers/sportium.py, betfair.py,
# winamax.py) y mezclar ambas fuentes para la misma casa arriesga comparar
# una cuota fresca (scraping directo) con una del comparador que puede ir
# unos segundos/minutos por detrás.
ALLOWED_BOOKMAKERS = {
    "1xbet.es": "1xbet",
    "888sport": "888sport",
    "bet365": "bet365",
    "betway": "betway",
    "bwin.es": "bwin",
    "codere": "codere",
    "luckia.es": "luckia",
    "paf.es": "paf",
    "retabet": "retabet",
    "speedybet.es": "speedybet",
    "versus.es": "versus",
    "william hill": "williamhill",
}

# Pestañas de mercado adicionales a la 1X2 (que ya viene seleccionada por
# defecto al cargar la página del partido) que son tabla plana de un único
# resultado por casa (sin líneas que agrupar, a diferencia de "Más/Menos de"
# y los dos hándicaps, que usan un acordeón por línea - ver
# _ACCORDION_MARKETS). "Marcador correcto" y "Descanso/Final" quedan fuera a
# propósito: la primera por riesgo de falso positivo entre casas con
# conjuntos de resultados distintos (mismo bug documentado en el README), la
# segunda por resultar ser un acordeón por combinación (9 filas, poca
# cobertura) en vez de tabla plana.
# Clave = texto exacto del botón de pestaña, valor = market_type resultante.
EXTRA_MARKET_TABS: dict[str, str] = {
    "Ambos equipos marcan": "BTTS",
    "Doble oportunidad": "DC",
    # Añadidas 2026-09-16, mismo mecanismo que BTTS/DC (tabla plana,
    # confirmado en vivo antes de añadirlas): "Resultado sin empate" (quién
    # gana sin contar el empate) y "Par/Impar" (total de goles par o impar).
    # "Descanso/Final" se probó también pero resultó ser un acordeón por
    # combinación (9 filas a expandir, poca cobertura) en vez de tabla
    # plana, así que se deja fuera — no encaja en este mecanismo.
    #
    # LIMITACIÓN CONOCIDA: ambas viven detrás del desplegable "Más" (a
    # diferencia de BTTS/DC, que son pestañas directamente visibles), y
    # `_click_tab` solo consigue abrirlo de forma fiable en una sesión de
    # navegador ya "usada" (con cookies previas). En una sesión Playwright
    # nueva -sin cookies, como la de producción- se comprobó en vivo el
    # 2026-09-16 contra Premier League que el botón "Más" no aparece en el
    # DOM de la misma forma (probablemente una plantilla distinta para
    # visitantes anónimos), así que estas dos pestañas fallan en silencio
    # (log de warning, sin cortar el resto del scraping) más a menudo de lo
    # ideal. Se dejan igualmente porque no rompen nada cuando fallan y sí
    # aportan cuando el desplegable sí se abre, pero no dar por hecho que
    # `market_type in {"DNB", "OE"}` vaya a aparecer siempre.
    "Resultado sin empate": "DNB",
    "Par/Impar": "OE",
}

# Cada pestaña de mercado (1X2, Ambos equipos marcan, Más/Menos de...) tiene
# además un sub-filtro de periodo ("Final del partido" | "1er tiempo" |
# "2º tiempo") que cambia la tabla mostrada sin cambiar de pestaña -
# verificado en vivo el 2026-09-17: "1er tiempo" en la pestaña 1X2 da un
# resultado de descanso real (p.ej. 3.94/2.35/2.46), distinto y no derivable
# del resultado a final de partido, con cobertura de casas similar (12-15).
# Es un mecanismo distinto de "Descanso/Final" (EXTRA_MARKET_TABS más
# arriba, descartado por ser acordeón de 9 combinaciones): aquí es la MISMA
# tabla plana de siempre, solo que preguntando por un periodo del partido.
#
# Solo se implementa "1er tiempo" (no "2º tiempo") para las dos pestañas más
# lucrativas para arbitraje (1X2 y BTTS), no para todas las pestañas ni todas
# las líneas de "Más/Menos de"/hándicaps: cada mercado con periodo exige un
# click de pestaña + un click de periodo + una lectura estable (ver
# _switch_market_tab_with_period), así que ampliarlo a todo dispararía el
# tiempo de escaneo por partido para un beneficio marginal decreciente - ver
# README "Nota de rendimiento".
#
# IMPORTANTE: cambiar de pestaña reinicia el periodo a "Final del partido"
# (confirmado en vivo: tras seleccionar "1er tiempo" en Más/Menos de y
# cambiar a 1X2, la tabla volvió a ser la de partido completo), así que hay
# que volver a hacer click en "1er tiempo" cada vez, no basta con hacerlo una
# vez por partido.
HALF_TIME_MARKET_TABS: dict[str, str] = {
    "1X2": "1X2_HT",
    "Ambos equipos marcan": "BTTS_HT",
}

# _fetch_match no distingue deporte al recorrer HALF_TIME_MARKET_TABS (mismo
# código para todos), pero el sub-filtro de periodo NO está disponible por
# igual en todos - verificado en vivo el 2026-09-17 contra un partido real de
# cada deporte:
#   - "1X2" con "1er tiempo": fútbol, balonmano, béisbol (ahí es en realidad
#     "primeras 5 entradas", pero mismo botón/mecanismo) y fútbol americano
#     SÍ lo tienen, con datos reales y distintos del partido completo en los
#     cuatro. Baloncesto NO: ni "1X2" ni "Local/Visitante" ofrecen ningún
#     sub-filtro de periodo (el único que aparece es "Final del partido
#     incluyendo prórroga") - los cuartos solo existen dentro del acordeón
#     "Más/Menos de", un mecanismo distinto que no se ha implementado.
#   - "Ambos equipos marcan" con "1er tiempo": solo fútbol. Balonmano y
#     béisbol no tienen pestaña BTTS en absoluto (ya documentado). Fútbol
#     americano SÍ tiene la pestaña BTTS, pero verificado en vivo que ESA
#     pestaña en concreto no tiene sub-filtro de periodo (solo 1X2 lo tiene).
#
# Sin este mapa, baloncesto intentaría (y fallaría, con warning) los dos
# clicks de periodo en cada partido sin ninguna posibilidad de éxito -
# tiempo de escaneo desperdiciado sin ningún beneficio, así que se excluye
# explícitamente en vez de dejar que falle en silencio como con DNB/OE.
HALF_TIME_SPORT_EXCLUSIONS: dict[str, set[str]] = {
    "1X2_HT": {"baloncesto"},
    "BTTS_HT": {"baloncesto", "balonmano", "beisbol", "americano"},
}

# Misma tabla HTML para cualquier pestaña (1X2, BTTS, Doble oportunidad):
# primera columna = casa, última columna = payout%, columnas del medio = una
# cuota por resultado. En vez de fijar los nombres de resultado a mano por
# mercado, se leen del <thead> (p.ej. ["Bookmakers","Yes","No","Payout"] para
# BTTS, ["Bookmakers","1X","12","X2","Payout"] para Doble oportunidad) -
# verificado en vivo el 2026-09-16 que la cabecera siempre coincide en número
# y orden con las columnas de cuota de cada fila.
_EXTRACT_ODDS_TABLE_JS = """() => {
    const table = document.querySelector('table');
    if (!table) return { headers: [], rows: [] };
    const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    const rows = Array.from(table.querySelectorAll('tbody tr')).map(row => {
        const cells = Array.from(row.querySelectorAll('td'));
        if (cells.length < 3) return null;
        const nameEl = cells[0].querySelector('p');
        return {
            bookmaker: (nameEl ? nameEl.textContent : cells[0].textContent).trim(),
            odds: cells.slice(1, -1).map(td => td.textContent.trim()),
        };
    }).filter(Boolean);
    return { headers, rows };
}"""

# Nº máximo de líneas por pestaña en acordeón (Más/Menos de, Hándicap
# asiático, Hándicap europeo) que se expanden por partido. Cada pestaña es un
# acordeón: cada línea (p.ej. "+2.5") es una fila resumen que hay que hacer
# click para revelar su propia tabla por casa (ver _fetch_accordion_market).
# Un partido puede tener 15-20 líneas, pero el grueso de la cobertura de
# casas se concentra en 2-3 líneas estándar - expandirlas todas multiplicaría
# el tiempo de scraping por partido sin aportar casi ninguna surebet
# adicional, así que solo se expanden las `ACCORDION_MAX_LINES` líneas con
# más casas.
ACCORDION_MAX_LINES = 3

# Pestañas de mercado en acordeón por línea (a diferencia de EXTRA_MARKET_TABS,
# que son tablas planas de un único resultado por casa): cada una tiene una
# fila resumen por línea ("Más/Menos de +2.5", "Hándicap asiático -1.5"...)
# que hay que expandir para ver la tabla por casa. Verificado en vivo
# 2026-09-17 contra fútbol (LaLiga) y baloncesto (NBA): misma estructura DOM
# en los tres casos (fila <tr class="cursor-pointer"> + tabla anidada en el
# <tr> hermano siguiente), solo cambian el texto de la pestaña/prefijo de
# línea y las columnas de resultado.
#
# - "Más/Menos de" (goles/puntos/juegos): 2 resultados "Over"/"Under",
#   siempre visible como pestaña directa. Línea siempre positiva ("+2.5"):
#   se le quita el signo al normalizar (ver _parse_accordion_table) para
#   casar con la convención "OU_2.5" que ya usan Sportium/Betfair.
# - "Hándicap asiático": 2 resultados "1"/"2" (sin empate posible, es una
#   línea fraccionaria), siempre visible como pestaña directa. Línea con
#   signo relevante ("-1.75" y "+1.75" son mercados distintos): NO se
#   normaliza el signo.
# - "Hándicap europeo": 3 resultados "1"/"X"/"2" (línea entera, sí cabe
#   empate en la línea 0, aunque CuotasAhora no ofrece la línea 0 en esta
#   pestaña - probablemente porque coincide con 1X2 sin hándicap). Vive
#   detrás del desplegable "Más" (igual que DNB/OE, ver EXTRA_MARKET_TABS):
#   misma limitación conocida de fiabilidad del click en sesión nueva.
_ACCORDION_MARKETS: list[dict] = [
    {"tab_label": "Más/Menos de", "prefix": "Más/Menos de", "market_prefix": "OU", "strip_sign": True, "behind_more": False},
    {"tab_label": "Hándicap asiático", "prefix": "Hándicap asiático", "market_prefix": "AH", "strip_sign": False, "behind_more": False},
    {"tab_label": "Hándicap europeo", "prefix": "Hándicap europeo", "market_prefix": "EH", "strip_sign": False, "behind_more": True},
]

# Cada línea de un acordeón es una <tr class="cursor-pointer"> cuyo texto de
# resumen (p.ej. "Más/Menos de +2.5") vive en un <span> hoja aparte del
# contador de casas (otro <span> con solo dígitos en la misma <td>) -
# verificado en vivo el 2026-09-16: si se leyera el texto completo de la fila
# de un tirón, "+2.5" y el contador "13" quedarían pegados ("+2.513") sin
# separador, así que se buscan como dos nodos hoja distintos dentro de la
# misma <td> en vez de trocear un único string. `prefix` se recibe como
# argumento (en vez de estar fijo en el JS) para reutilizar el mismo bloque
# con "Más/Menos de", "Hándicap asiático" y "Hándicap europeo".
_EXTRACT_ACCORDION_LINES_JS = """(prefix) => {
    const escaped = prefix.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
    const re = new RegExp('^' + escaped + ' [+-]?\\\\d+(?:\\\\.\\\\d+)?$');
    const labelLeaves = Array.from(document.querySelectorAll('table tbody > tr.cursor-pointer *'))
        .filter(e => e.children.length === 0 && re.test(e.textContent.trim()));
    return labelLeaves.map(leaf => {
        const line = leaf.textContent.trim().slice(prefix.length + 1);
        const td = leaf.closest('td');
        let count = 0;
        if (td) {
            const numLeaf = Array.from(td.querySelectorAll('*')).find(
                e => e.children.length === 0 && e !== leaf && /^\\d+$/.test(e.textContent.trim())
            );
            if (numLeaf) count = parseInt(numLeaf.textContent.trim(), 10);
        }
        return { line, count };
    });
}"""

# Hace click en la fila resumen de una línea concreta (comparación exacta del
# valor de línea, no por substring: "+1" y "+1.25" comparten prefijo y un
# selector de texto de Playwright los confundiría). Devuelve false si la
# línea ya no está en el DOM (partido actualizado/cerrado entre medias).
_CLICK_ACCORDION_LINE_JS = """([prefix, line]) => {
    const escaped = prefix.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
    const re = new RegExp(escaped + ' ([+-]?\\\\d+(?:\\\\.\\\\d+)?)');
    const rows = Array.from(document.querySelectorAll('table tbody > tr.cursor-pointer'));
    const tr = rows.find(r => {
        const m = r.textContent.match(re);
        return m && m[1] === line;
    });
    if (!tr) return false;
    tr.click();
    return true;
}"""

# Tras el click, la fila resumen revela una tabla anidada en el <tr> hermano
# siguiente (misma forma que _EXTRACT_ODDS_TABLE_JS: Bookmakers/.../Payout,
# pero con una columna extra de por medio - "Total" en Más/Menos de,
# "Handicap" en los dos hándicaps - con la línea repetida en vez de una
# cuota; se filtra en Python por nombre de columna, no por posición, en
# _parse_accordion_table).
_EXTRACT_ACCORDION_TABLE_FOR_LINE_JS = """([prefix, line]) => {
    const escaped = prefix.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
    const re = new RegExp(escaped + ' ([+-]?\\\\d+(?:\\\\.\\\\d+)?)');
    const rows = Array.from(document.querySelectorAll('table tbody > tr.cursor-pointer'));
    const tr = rows.find(r => {
        const m = r.textContent.match(re);
        return m && m[1] === line;
    });
    const detailTr = tr ? tr.nextElementSibling : null;
    const table = detailTr ? detailTr.querySelector('table') : null;
    if (!table) return { headers: [], rows: [] };
    const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    const rowsData = Array.from(table.querySelectorAll('tbody tr')).map(row => {
        const cells = Array.from(row.querySelectorAll('td'));
        if (cells.length < 3) return null;
        const nameEl = cells[0].querySelector('p');
        return {
            bookmaker: (nameEl ? nameEl.textContent : cells[0].textContent).trim(),
            odds: cells.slice(1, -1).map(td => td.textContent.trim()),
        };
    }).filter(Boolean);
    return { headers, rows: rowsData };
}"""

# Abre el desplegable "Más" de pestañas de mercado. Se localiza y clica por
# JS (no con un selector de texto de Playwright) porque ":text-is('Más')"
# resultó poco fiable en vivo el 2026-09-16 (timeout constante) para
# distinguirlo de "Más/Menos de", pese a que el botón sí existe y es
# clicable - la comparación de texto exacta en JS no tiene ese problema.
_CLICK_MORE_DROPDOWN_JS = """() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => {
        const text = b.textContent.trim();
        return text === 'Más' || (text.startsWith('Más') && text.length <= 6 && !text.includes('/'));
    });
    if (!btn) return false;
    btn.click();
    return true;
}"""


class CuotasAhoraProvider(OddsProvider):
    """Scraper por DOM (Playwright) de cuotasahora.com (versión española de
    OddsPortal): comparador que agrega cuotas de muchas casas en una sola
    tabla por partido, en vez de una casa por sitio.

    Verificado en vivo: página de liga (.../laliga-ea-sports/) sin bloqueo
    anti-bot, solo dos gates estándar de UI a aceptar una vez por sesión de
    navegador (verificación de edad 18+ y el banner de cookies OneTrust,
    igual que en Betfair). Cada partido tiene su propia página
    (/football/h2h/equipo-a/equipo-b/) con una única <table> HTML (no CSS
    modules ni clases con hash) listando cuota 1/X/2 por casa, más pestañas
    para otros mercados (ver EXTRA_MARKET_TABS) que reutilizan la misma
    tabla.

    Su propia API de datos (proxy/ajax-nextgames-odds/...) devuelve la
    respuesta cifrada a propósito (base64 de contenido encriptado) para
    dificultar el scraping de la API - por eso se lee el DOM ya renderizado
    (la propia página lo descifra en el navegador para mostrarlo), igual que
    con el resto de proveedores, en vez de intentar romper ese cifrado.

    `league_urls` acepta varias claves de competición por deporte (p.ej.
    "futbol" para LaLiga y "futbol_champions" para la Champions League): cada
    clave es un "sport" independiente de cara al motor de arbitraje, así que
    conviene pasar ambas en la lista `sports` del ciclo de escaneo si se
    quiere cobertura de las dos. Se mantienen en el mismo `sport="futbol"` en
    el Market resultante (ver `_fetch_match`) porque el motor no necesita
    distinguir competición, solo evento+mercado.
    """

    name = "cuotasahora"

    def __init__(self, league_urls: dict[str, str] | None = None):
        self.league_urls = league_urls or DEFAULT_LEAGUE_URLS

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for sport_key in sports:
                url = self.league_urls.get(sport_key)
                if not url:
                    continue
                # sport_key puede ser "futbol_champions" etc. (una clave de
                # competición distinta por URL), pero de cara al motor de
                # arbitraje todo esto es el mismo deporte: se normaliza al
                # deporte real para poder cruzar eventos con el resto de
                # proveedores.
                sport = sport_key.split("_", 1)[0]
                sport_path = SPORT_URL_SEGMENT.get(sport, "football")
                match_urls = await self._collect_match_urls(page, url, sport_path)
                if not match_urls:
                    logger.warning(
                        "CuotasAhora: 0 partidos encontrados en %s (title=%r) - "
                        "puede que el gate de edad/cookies no se haya cerrado o la web esté bloqueando el runner",
                        url,
                        await page.title(),
                    )
                for match_url in match_urls:
                    markets.extend(await self._fetch_match(page, match_url, sport))
            await browser.close()
        return markets

    async def _dismiss_gates(self, page) -> None:
        for selector in ("text=Soy mayor de 18", "#onetrust-reject-all-handler"):
            try:
                await page.click(selector, timeout=3000)
            except Exception:
                pass

    async def _collect_match_urls(self, page, league_url: str, sport_path: str = "football") -> list[str]:
        await page.goto(league_url, timeout=20000)
        await page.wait_for_timeout(1200)
        await self._dismiss_gates(page)
        await page.wait_for_timeout(800)
        hrefs = await page.eval_on_selector_all(
            f'a[href*="/{sport_path}/h2h/"]', "els => els.map(e => e.getAttribute('href'))"
        )
        anchor = f"/{sport_path}/h2h/"
        seen = set()
        urls = []
        for href in hrefs:
            if not href:
                continue
            # Algunos partidos ya en juego aparecen en el mismo listado que
            # los de pre-partido, pero con "/inplay-odds/" en la URL (visto
            # en vivo el 2026-09-17 en el listado de béisbol, con partidos de
            # MLB en curso mezclados con los de después). Se descartan
            # explícitamente: este sistema es solo pre-partido a propósito
            # (ver README "Mercados soportados") y las cuotas en directo
            # cambian demasiado rápido para el margen de tiempo que asume el
            # resto del pipeline (dedupe de oportunidades activas, etc.).
            if "inplay-odds" in href:
                continue
            # Algunos enlaces vienen con un prefijo de locale delante del
            # segmento de deporte (p.ej. "/pl/football/h2h/...", visto en
            # vivo el 2026-09-16 en la Premier League) que la propia web no
            # resuelve bien si se navega directo a esa URL con Playwright
            # (redirige al hub genérico en vez de al partido). Se recorta
            # todo lo anterior al segmento de deporte para quedarnos siempre
            # con la forma canónica "/<deporte>/h2h/...".
            idx = href.find(anchor)
            if idx == -1:
                continue
            href = href[idx:]
            absolute = urllib.parse.urljoin(league_url, href)
            key = absolute.split("#")[0]
            if key in seen:
                continue
            seen.add(key)
            urls.append(absolute)
        return urls

    async def _fetch_match(self, page, match_url: str, sport: str) -> list[Market]:
        try:
            await page.goto(match_url, timeout=20000)
            await page.wait_for_selector("table", timeout=15000)
            await page.wait_for_timeout(1500)

            body_text = await page.inner_text("body")
            if "Resultado final" in body_text:
                return []  # partido ya jugado, no sirve para arbitraje en vivo

            # El selector de nombres de equipo usado hasta ahora
            # ("a.min-w-0.self-center.truncate") ya no existe en el DOM
            # actual (verificado en vivo 2026-09-16, ver checklist.md). El
            # <h1> parecía un reemplazo limpio ("Equipo A - Equipo B") en
            # pruebas manuales, pero resultó no ser fiable: en una ejecución
            # real de Playwright (sin cookies/sesión previas) algunos
            # partidos devuelven un <h1> mucho más largo, tipo SEO
            # ("Equipo A vs Equipo B - Cuotas, predicciones y resultados
            # H2H..."), probablemente una plantilla server-side distinta para
            # visitantes nuevos. El <title> de la página, en cambio, mantuvo
            # siempre el mismo formato en todas las pruebas en vivo
            # (fútbol, baloncesto, varias ligas): "Cuotas de Equipo A -
            # Equipo B, pronósticos e historial de enfrentamientos |
            # CuotasAhora" - se usa ese patrón en vez del <h1>.
            title = await page.title()
            match = re.match(r"^Cuotas de (.+?) - (.+?), pron[oó]sticos", title)
            if not match:
                return []
            home, away = match.group(1).strip(), match.group(2).strip()

            table_data = await page.evaluate(_EXTRACT_ODDS_TABLE_JS)
        except Exception:
            logger.warning("CuotasAhora: fallo cargando partido %s", match_url, exc_info=True)
            return []

        markets = []
        market = self._parse_match(home, away, table_data, "1X2", sport)
        if market is not None:
            markets.append(market)
        elif table_data.get("rows"):
            logger.warning(
                "CuotasAhora: %s devolvió %d filas pero ninguna casó con ALLOWED_BOOKMAKERS/odds válidas: %r",
                match_url,
                len(table_data["rows"]),
                [r.get("bookmaker") for r in table_data["rows"]],
            )

        for tab_label, market_type in EXTRA_MARKET_TABS.items():
            extra_table_data = await self._switch_market_tab(page, tab_label)
            if extra_table_data is None:
                continue
            extra_market = self._parse_match(home, away, extra_table_data, market_type, sport)
            if extra_market is not None:
                markets.append(extra_market)

        for tab_label, market_type in HALF_TIME_MARKET_TABS.items():
            if sport in HALF_TIME_SPORT_EXCLUSIONS.get(market_type, set()):
                continue
            ht_table_data = await self._switch_market_tab_with_period(page, tab_label, "1er tiempo")
            if ht_table_data is None:
                continue
            ht_market = self._parse_match(home, away, ht_table_data, market_type, sport)
            if ht_market is not None:
                markets.append(ht_market)

        for spec in _ACCORDION_MARKETS:
            markets.extend(await self._fetch_accordion_market(page, home, away, sport, spec))

        return markets

    async def _fetch_accordion_market(
        self, page, home: str, away: str, sport: str, spec: dict
    ) -> list[Market]:
        """Pestañas en acordeón (Más/Menos de, Hándicap asiático, Hándicap
        europeo): a diferencia de BTTS/DC/DNB/OE no son tablas planas, cada
        una tiene una fila resumen por línea que hay que expandir una a una
        (ver constantes _EXTRACT_ACCORDION_LINES_JS/_CLICK_ACCORDION_LINE_JS/
        _EXTRACT_ACCORDION_TABLE_FOR_LINE_JS). Solo se expanden las
        ACCORDION_MAX_LINES líneas con más casas, no todas, para no disparar
        el tiempo de scraping por partido. `spec` es una entrada de
        _ACCORDION_MARKETS.
        """
        prefix = spec["prefix"]
        try:
            if spec["behind_more"]:
                await self._click_tab(page, spec["tab_label"])
            else:
                await page.click(f'button:has-text("{spec["tab_label"]}")', timeout=5000)
            await page.wait_for_timeout(600)
            lines = await page.evaluate(_EXTRACT_ACCORDION_LINES_JS, prefix)
        except Exception:
            return []

        top_lines = sorted(lines, key=lambda item: item.get("count", 0), reverse=True)[:ACCORDION_MAX_LINES]

        markets = []
        for item in top_lines:
            line = item.get("line")
            if not line:
                continue
            try:
                clicked = await page.evaluate(_CLICK_ACCORDION_LINE_JS, [prefix, line])
                if not clicked:
                    continue
                await page.wait_for_timeout(500)
                table_data = await page.evaluate(_EXTRACT_ACCORDION_TABLE_FOR_LINE_JS, [prefix, line])
            except Exception:
                continue
            market = self._parse_accordion_table(home, away, table_data, line, sport, spec)
            if market is not None:
                markets.append(market)
        return markets

    def _parse_accordion_table(
        self, home: str, away: str, table_data: dict, line: str, sport: str, spec: dict
    ) -> Market | None:
        headers = table_data.get("headers", [])
        # "Más/Menos de" usa "Over"/"Under"; los dos hándicaps usan "1"/"2"
        # (asiático, sin empate posible) o "1"/"X"/"2" (europeo, línea
        # entera) - mismos nombres que ya usa 1X2/DC, así que basta con
        # buscar cualquiera de los dos juegos de nombres por columna.
        outcome_names = [h for h in headers if h in ("Over", "Under", "1", "X", "2")]
        if not outcome_names:
            return None
        outcomes = []
        for row in table_data.get("rows", []):
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row.get("bookmaker", "").strip().lower())
            if bookmaker_key is None:
                continue
            odds = row.get("odds", [])
            values = []
            try:
                # `odds` no incluye la columna "Bookmakers" (índice 0 de
                # `headers`), así que cada índice de columna se desplaza -1.
                for name in outcome_names:
                    values.append(float(odds[headers.index(name) - 1]))
            except (IndexError, ValueError):
                continue
            outcomes.extend(
                Outcome(name=name, bookmaker=bookmaker_key, odds=value)
                for name, value in zip(outcome_names, values)
            )
        if not outcomes:
            return None
        event_name = f"{home} vs. {away}"
        normalized_line = line.lstrip("+") if spec["strip_sign"] else line
        market_type = f"{spec['market_prefix']}_{normalized_line}"
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)

    async def _switch_market_tab(self, page, tab_label: str) -> dict | None:
        try:
            await self._click_tab(page, tab_label)
            return await self._read_table_when_stable(page)
        except Exception:
            logger.warning("CuotasAhora: fallo cambiando a la pestaña %r", tab_label, exc_info=True)
            return None

    async def _switch_market_tab_with_period(
        self, page, tab_label: str, period_label: str
    ) -> dict | None:
        """Como _switch_market_tab, pero además selecciona un periodo del
        partido ("1er tiempo"/"2º tiempo") dentro de esa pestaña - ver
        HALF_TIME_MARKET_TABS. El botón de periodo es directamente visible
        (a diferencia de "Más"), así que no hace falta el fallback de
        desplegable de _click_tab.
        """
        try:
            await self._click_tab(page, tab_label)
            await page.click(f'button:has-text("{period_label}")', timeout=3000)
            return await self._read_table_when_stable(page)
        except Exception:
            logger.warning(
                "CuotasAhora: fallo seleccionando %r en la pestaña %r", period_label, tab_label, exc_info=True
            )
            return None

    async def _click_tab(self, page, tab_label: str) -> None:
        """Hace click en una pestaña de mercado por su texto exacto.

        Algunas pestañas ("Resultado sin empate", "Par/Impar"...) no están
        entre las visibles por defecto: viven detrás del desplegable "Más" -
        verificado en vivo el 2026-09-16 contra un partido de Premier League:
        el <button> existe en el DOM incluso con el desplegable cerrado, pero
        no es clicable (display:none) hasta abrirlo, así que un primer
        intento directo falla en silencio (timeout) para esas pestañas.
        """
        try:
            await page.click(f'button:has-text("{tab_label}")', timeout=2500)
            return
        except Exception:
            pass
        # El selector de texto de Playwright (":text-is()") resultó poco
        # fiable en vivo para distinguir el botón "Más" de "Más/Menos de"
        # (timeout constante pese a que el botón sí existe), así que se
        # localiza y clica por JS con una comparación exacta de texto -
        # mismo enfoque que ya usan _CLICK_OU_LINE_JS y compañía.
        opened = await page.evaluate(_CLICK_MORE_DROPDOWN_JS)
        if not opened:
            raise RuntimeError('No se encontró el botón "Más" del desplegable de mercados')
        await page.wait_for_timeout(300)
        await page.click(f'button:has-text("{tab_label}")', timeout=5000)

    async def _read_table_when_stable(self, page) -> dict:
        # Tras cambiar de pestaña, la cabecera se actualiza al instante pero
        # cada fila (casa) refresca su propia cuota de forma independiente y
        # con retardo variable - un wait_for_timeout(800) fijo a veces lee la
        # tabla a medio refrescar: la cabecera ya dice p.ej. "Yes"/"No" pero
        # alguna fila concreta (no siempre la misma) todavia arrastra el
        # numero de la pestaña anterior (1X2), coincidiendo por casualidad en
        # numero de columnas y coandolando un "margen" disparatado (~70%)
        # como si fuera una surebet real. Confirmado en vivo el 2026-09-16
        # contra cuotasahora.com: bet365/retabet mostraban en "Ambos equipos
        # marcan" los mismos valores que sus columnas "1"/"X" de la pestaña
        # 1X2. Se espera a que dos lecturas consecutivas coincidan para dar
        # la tabla por asentada, en vez de fiarse de un tiempo fijo.
        previous = None
        for _ in range(8):
            await page.wait_for_timeout(400)
            current = await page.evaluate(_EXTRACT_ODDS_TABLE_JS)
            if current == previous:
                return current
            previous = current
        return previous

    def _parse_match(
        self, home: str, away: str, table_data: dict, market_type: str, sport: str
    ) -> Market | None:
        headers = table_data.get("headers", [])
        # La cabecera es ["Bookmakers", <resultado 1>, ..., "Payout"]: los
        # nombres de resultado son todo lo que queda al quitar esas dos.
        outcome_names = headers[1:-1] if len(headers) >= 3 else []
        if not outcome_names:
            return None
        outcomes = []
        for row in table_data.get("rows", []):
            bookmaker_key = ALLOWED_BOOKMAKERS.get(row.get("bookmaker", "").strip().lower())
            if bookmaker_key is None:
                continue
            odds = row.get("odds", [])
            if len(odds) != len(outcome_names):
                continue
            try:
                values = [float(o) for o in odds]
            except ValueError:
                continue
            outcomes.extend(
                Outcome(name=name, bookmaker=bookmaker_key, odds=value)
                for name, value in zip(outcome_names, values)
            )
        if not outcomes:
            return None
        event_name = f"{home} vs. {away}"
        return Market(event=event_name, sport=sport, market_type=market_type, outcomes=outcomes)
