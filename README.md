# Surebets

Sistema propio de detección de arbitraje deportivo (surebets), pensado para arrancar con coste mínimo.

Basado en:
- [Arbitraje deportivo y surebets: guía técnica y práctica](<Arbitraje deportivo y surebets  guía técnica y práctica para montar un sistema asistido por IA.md>)
- [Cómo montar un sistema ligero de detección de surebets con coste mínimo](<Cómo montar un sistema ligero de detección de surebets con coste mínimo.md>)
- [Arquitectura actual y transición de tu proyecto de surebets con GitHub Actions, web en GitHub y bot de Telegram](<Arquitectura actual y transición de tu proyecto de surebets con GitHub Actions, web en GitHub y bot de Telegram.md>)
- [Métodos para obtener cuotas deportivas en tiempo real: scraping vs APIs agregadas vs feeds](<Métodos para obtener cuotas deportivas en tiempo real  scraping vs APIs agregadas vs feeds.md>)

## Arquitectura

```
engine/               motor matemático: detección de surebets, margen, cálculo de stakes, y el ciclo de
                      escaneo (scan.py) reutilizado tanto por main.py como por scripts/scan_once_action.py
providers/            fuentes de cuotas (interfaz OddsProvider). mock.py es un proveedor de ejemplo para pruebas.
storage/              SQLite: registro de oportunidades detectadas
bot/                  bot de Telegram (/hoy, /ahora, /stats)
main.py               orquestador de larga duración: fetch periódico -> detección -> guardado -> aviso (VM + systemd)
scripts/              scan_once_action.py: un solo ciclo de escaneo, pensado para GitHub Actions
.github/workflows/    workflow programado que ejecuta scripts/scan_once_action.py cada 15 min
```

El motor (`engine/`) no sabe nada de Telegram ni de scraping: por eso el mismo core podrá alimentar más adelante
un panel web sin reescribir la lógica de arbitraje.

## Puesta en marcha

```bash
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edita `.env`:
- `TELEGRAM_BOT_TOKEN`: crea un bot con [@BotFather](https://t.me/BotFather) en Telegram (`/newbot`) y pega el token aquí. **No lo compartas ni lo subas a git.**
- `TELEGRAM_CHAT_ID`: tu chat id (envía un mensaje a tu bot y consulta `https://api.telegram.org/bot<TOKEN>/getUpdates` para obtenerlo), para recibir avisos automáticos de nuevas surebets.
- `BANKROLL`: banca a repartir en cada oportunidad (por defecto 250€).
- `MIN_MARGIN`: margen mínimo para considerar una oportunidad relevante (por defecto 0.01 = 1%).

Arrancar:

```bash
.venv\Scripts\python main.py
```

Con el proveedor `mock` de ejemplo, el bot detectará una surebet ficticia (Djokovic/Alcaraz, cuotas 2.00/2.05) y
responderá a los comandos `/hoy`, `/ahora` y `/stats` en Telegram.

## Despliegue 24/7 (sin depender de tu PC)

Dos opciones documentadas paso a paso en [deploy/README_DEPLOY.md](deploy/README_DEPLOY.md):
GitHub Actions (gratis, sin tarjeta, solo avisos push) o una VM propia con systemd (Hetzner de pago,
u Oracle Cloud Always Free) con el bot completo incluyendo `/hoy`, `/ahora` y `/stats`.

## Tests

```bash
.venv\Scripts\python -m pytest
```

## Estado actual y próximos pasos

**Hecho (MVP fase 0):**
- Motor de arbitraje (`engine/arbitrage.py`) con tests, validado contra el ejemplo del documento base.
- Interfaz de proveedores de cuotas (`providers/base.py`) desacoplada, con un proveedor mock para probar el flujo completo.
- `engine/matching.py`: agrupa el mismo evento/mercado entre casas distintas (aunque el nombre del equipo varíe) y se queda con la mejor cuota de cada resultado antes de evaluar el arbitraje.
- Almacenamiento SQLite de oportunidades detectadas.
- Bot de Telegram con comandos `/hoy`, `/ahora`, `/stats` y avisos automáticos.

### Estado real de los scrapers (verificado en vivo, no teórico)

| Casa | Estado | Detalle |
|---|---|---|
| **Sportium** | ✅ Funciona (`providers/sportium.py`) | Playwright headless normal, sin trucos. 1X2 y over/under (Goles Totales) en vivo verificados. |
| **Betfair** | ✅ Funciona (`providers/betfair.py`) | Playwright headless normal. 1X2 y over/under 2,5 goles en vivo verificados sobre el listado completo de LaLiga. |
| **Winamax** | ✅ Funciona (`providers/winamax.py`) | Playwright headless normal. Cuotas en coma decimal española, convertidas a float. Solo 1X2: el over/under no está en la página de listado, solo en la ficha de cada partido (requeriría una petición extra por partido). |
| **CuotasAhora.com** (comparador) | ✅ Funciona (`providers/cuotasahora.py`) | Playwright headless. No es una casa, es un comparador (versión española de OddsPortal) que agrega 1X2 de ~14 casas por partido en una sola tabla HTML. Ver detalle abajo — es la vía por la que se desbloquean, indirectamente, bet365/bwin/Codere/Luckia/William Hill. |
| **BetExplorer.com** (comparador, nuevo 2026-09-17) | ✅ Funciona (`providers/betexplorer.py`) | Playwright headless. Segundo comparador, empresa distinta a CuotasAhora/OddsPortal. Mismas casas DGOJ, tablas HTML semánticas (más simples de leer que CuotasAhora). Ver detalle abajo. |
| **Jokerbet, Pastón, Betway** (plataforma Altenar, nuevo 2026-09-20) | ✅ Funciona (`providers/altenar.py`) | API JSON pública de su widget, sin navegador. Córners, tarjetas, hándicaps y mercados por mitad pre-partido, que los comparadores no tienen. Ver detalle abajo. |
| **Paf, LeoVegas** (plataforma Kambi, nuevo 2026-09-20) | ✅ Funciona (`providers/kambi.py`) | API pública de ofertas de Kambi, sin navegador. Fuente **directa** de la casa (no comparador): mismos mercados extra que Altenar (córners, tarjetas, faltas, hándicaps, por mitad) pero otra plataforma y otros precios, lo que permite arbitraje entre plataformas. Ver detalle abajo. |
| **Interwetten, PokerStars** | ❌ Sin fuente | No aparecen en el catálogo de CuotasAhora ni de BetExplorer, ni usan Altenar/Kambi (PokerStars no expone ninguna de las dos en su web; Interwetten devuelve 403 y además Cloudflare bloquea el scraping directo). |
| **Speedybet** | ⚠️ Solo vía comparadores | Su web dice usar Kambi (mismo grupo que Paf) pero no se encontró su código de operador (probados ~15 nombres, varios devolvieron 429 por límite de peticiones, no concluyente). Sigue entrando vía CuotasAhora/BetExplorer. |
| **bet365, bwin, Codere, Luckia, William Hill** | ⚠️ Indirecto, vía CuotasAhora.com / BetExplorer.com | Bloqueadas para scraping directo (ver causas abajo), pero sus cuotas 1X2 llegan igualmente a través de ambos comparadores. |
| **888sport, Betway, Retabet, Paf.es, Speedybet.es, Versus.es, 1xBet.es** | ✅ Vía CuotasAhora.com / BetExplorer.com | No probadas directamente, cubiertas de golpe a través de los comparadores. |
| **Kirolbet** | ⚠️ Implementado pero bloqueado (`providers/kirolbet.py`) | Akamai Bot Manager. Ver detalle abajo. |
| **Betsson** | ❌ Bloqueado | API antifraude propia. Ver detalle abajo. |
| **Suertia (OlyBet)** | ❌ Bloqueado a nivel de red | "Access Denied" del proveedor. Ver detalle abajo. |
| **Marca Apuestas** | ❌ Bloqueado | Cloudflare / 403 en API de cuotas. Ver detalle abajo. |
| **Interwetten** | ❌ Bloqueado | Cloudflare "Just a moment...". Ver detalle abajo. |
| **PokerStars Sports, Zebet, Botemanía** (Pastón ya funciona vía Altenar, ver arriba) | ❓ Sin confirmar para scraping directo, pero **ya con licencia DGOJ confirmada** (ver abajo) | Cargan sin bloqueo aparente, pero no se llegó a localizar/confirmar la tabla de cuotas real en el DOM. Candidatos a re-probar directamente (aunque ahora es menos prioritario, dado que CuotasAhora ya cubre muchas casas de golpe). |

✅ **Licencias DGOJ verificadas (2026-09-16)**: se contrastaron a mano las 78 fichas del buscador oficial
de operadores ([ordenacionjuego.es](https://www.ordenacionjuego.es/operadores-juego/operadores-licencia/operadores)).
**Todas** las casas usadas por este sistema (directas + vía CuotasAhora, incluido 1xBet.es) tienen licencia
vigente en España — la sospecha inicial de que 1xBet.es no la tuviera era incorrecta (licencia bajo WAGERFAIR,
S.A.). De paso se confirmó que Paston, Botemanía, Zebet y PokerStars Sports también están licenciadas
(EUROAPUESTAS ONLINE, GAMESYS SPAIN, ZEBETTING Y GAMING, TSG INTERACTIVE respectivamente), aunque su scraping
directo sigue sin confirmar. El panel web ([docs/](docs/)) marca en rojo cualquier casa que no esté en esta
lista verificada — hoy no debería salir ninguna en rojo; si sale alguna, es una señal de fallo de scraping o
de una casa nueva sin comprobar. Esta verificación es una foto de un momento dado (la DGOJ actualiza el
registro mensualmente) — revisar de nuevo si ha pasado mucho tiempo.

**Nota sobre verificación en vivo en este entorno de desarrollo (2026-09-17)**: al ampliar ligas/deportes de
CuotasAhora en esta sesión, el script de smoke-test con Playwright headless empezó a devolver 0 partidos/0
mercados de forma repetida (varias rondas, distintas ligas, incluso ligas ya en producción como la Premier
League) — timeouts esperando la tabla de cuotas o "Execution context was destroyed". Comparado en vivo con
el mismo partido navegado desde el propio panel de navegador de esta sesión (no el script automatizado): la
tabla de cuotas carga con normalidad. Conclusión: es throttling/limitación específica de las peticiones
automatizadas repetidas de este entorno de desarrollo concreto, no una regresión del sitio ni del código -
`docs/data.json` de escaneos de producción reales (vía `scripts/local_scan.ps1`, en la máquina del usuario)
siguen mostrando cientos de comparaciones con datos frescos el mismo día. Si se repite en el futuro: verificar
con el panel de navegador en vez de insistir con el script Playwright automatizado.

**5 fuentes reales funcionando** (Sportium, Betfair, Winamax + CuotasAhora.com y BetExplorer.com como comparadores) — entre ellas cubren más de 15 casas DGOJ distintas, suficiente para que el motor de arbitraje compare cuotas de verdad entre muchas casas. Validado en vivo: el cruce de eventos agrupa correctamente el mismo partido aunque cada casa lo nombre distinto ("At. Madrid" / "Atl. Madrid" / "Atlético de Madrid"), y **dos bugs reales de cruce de eventos** se detectaron y corrigieron con datos en vivo (no en teoría):
- Comparar el nombre completo del evento como un solo string confundía partidos distintos que comparten texto (p.ej. "Atlético Madrid vs. Osasuna" con "Atlético Madrid vs. Real Madrid", por la palabra común "Madrid").
- La similitud de texto genérica para nombres de equipo cortos daba falsos positivos (p.ej. "Barcelona" y "Celta" resultaron tener suficiente parecido de letras como para confundirse cuando ambos jugaban contra el mismo rival).

La solución fue una tabla de alias curada a mano para los 20 equipos de LaLiga (`engine/team_aliases.py`), en vez de depender solo de similitud de texto genérica. Sin estas dos correcciones, el sistema habría mostrado "surebets" del 30-40% que en realidad eran errores de comparación, no oportunidades reales — habría sido activamente engañoso.

### Mercados soportados

Además de 1X2, Sportium y Betfair scrapean también over/under de goles (verificado en vivo). Convención de
nombres: `market_type` es `"OU_<línea>"` (p.ej. `"OU_2.5"`) y los outcomes son `"Over"`/`"Under"`. Betfair
tiene la línea 2,5 como opción de menú fija, así que siempre es `OU_2.5`. Sportium sugiere una línea por
partido (normalmente 2,5, pero no siempre — puede ser 3,5 o 4,5 en partidos muy desnivelados), así que su
`market_type` varía por partido; al incluir la línea en el propio `market_type`, `group_by_event` nunca
compara por error una línea con otra. Winamax se queda solo en 1X2: su over/under no está en la página de
listado (donde vive todo lo demás), solo dentro de la ficha de cada partido, lo que exigiría una navegación
extra por partido — no implementado por ahora.

**CuotasAhora.com (`providers/cuotasahora.py`), además de 1X2, scrapea "Ambos equipos marcan"
(`market_type="BTTS"`, outcomes `"Yes"`/`"No"`), "Doble oportunidad" (`market_type="DC"`, outcomes
`"1X"`/`"12"`/`"X2"`), "Resultado sin empate" (`market_type="DNB"`, outcomes `"1"`/`"2"`), "Par/Impar"
(`market_type="OE"`, outcomes `"Odd"`/`"Even"`) y "Más/Menos de" (goles/puntos/juegos según deporte,
`market_type="OU_<línea>"` como Sportium/Betfair)** — verificado en vivo el 2026-09-16. Como es un
comparador que agrega ~12-14 casas por partido en la misma tabla, cada uno de estos mercados por sí solo ya
compara cuotas entre muchas casas (no depende de que otro proveedor cubra el mismo mercado). BTTS/DC/DNB/OE
se extraen igual: lee los nombres de resultado directamente de la cabecera `<thead>` de la tabla en vez de
tenerlos fijados a mano, así que añadir otra pestaña de mercado con la misma estructura de tabla plana es
cuestión de sumar una entrada a `EXTRA_MARKET_TABS`. Se probó también "Descanso/Final", pero resultó ser un
acordeón (como "Más/Menos de", ver abajo) con solo una casa de cobertura real por combinación — se dejó
fuera por no encajar en el mecanismo de tabla plana y aportar poco.

**Limitación conocida de DNB/OE**: a diferencia de BTTS/DC (pestañas siempre visibles), estas dos viven
detrás del desplegable "Más" del partido. Verificado en vivo el 2026-09-16: en una sesión de Playwright
recién arrancada (sin cookies, como la de producción) el botón "Más" no siempre aparece de la misma forma en
el DOM — probablemente una plantilla distinta para visitantes anónimos —, así que estas dos pestañas fallan
en silencio (con warning en el log) más a menudo de lo ideal. No cortan el resto del escaneo cuando fallan,
así que se dejaron activas, pero no des por hecho que `market_type` `"DNB"`/`"OE"` va a aparecer en cada
ciclo.

"Más/Menos de", "Hándicap asiático" y "Hándicap europeo" **sí** están implementados: los tres son un
acordeón por línea (p.ej. "+2.5", "-1.5", "-2") que hay que expandir haciendo click para revelar su tabla
por casa — `_fetch_accordion_market` en `providers/cuotasahora.py` generaliza el mismo mecanismo para los
tres (antes solo existía para Más/Menos de) y expande solo las `ACCORDION_MAX_LINES` (3) líneas con más
casas de cada partido, no todas (puede haber 15-20 líneas por partido; expandirlas todas dispararía el
tiempo de scraping sin aportar casi ninguna surebet adicional). La tabla expandida trae una columna extra
("Total" en Más/Menos de, "Handicap" en los dos hándicaps) con la línea repetida en vez de una cuota, que se
filtra por nombre de columna en vez de por posición, para no confundirla con un resultado más. Verificado en
vivo el 2026-09-17 contra LaLiga (fútbol) y NBA (baloncesto).

- **Hándicap asiático** (`market_type="AH_<línea>"`, outcomes `"1"`/`"2"`, sin empate posible): a diferencia
  de Más/Menos de, el signo de la línea es significativo ("AH_-1.5" y "AH_+1.5" son mercados distintos, no
  se le quita el signo al normalizar). Pestaña siempre visible, igual de fiable que Más/Menos de.
- **Hándicap europeo** (`market_type="EH_<línea>"`, outcomes `"1"`/`"X"`/`"2"`, línea entera): vive detrás
  del desplegable "Más", igual que DNB/OE — hereda la misma limitación de fiabilidad descrita justo arriba
  (falla en silencio más a menudo de lo ideal en una sesión de Playwright sin cookies).

**Mercados de 1er tiempo** (`market_type="1X2_HT"`/`"BTTS_HT"`, 2026-09-17): cada pestaña tiene además un
sub-filtro de periodo ("Final del partido" | "1er tiempo" | "2º tiempo") que da una tabla real y distinta
para el resultado al descanso — verificado en vivo con cobertura de 12-15 casas, similar a la de partido
completo. Es un mecanismo distinto de "Descanso/Final" (más abajo, descartado): aquí es la misma tabla plana
de siempre, solo preguntando por un periodo. Implementado solo para 1X2 y BTTS (las dos pestañas más
lucrativas), no para todas las pestañas/líneas ni para "2º tiempo": cambiar de pestaña reinicia el periodo a
"Final del partido" (confirmado en vivo), así que cada mercado con periodo cuesta un click de pestaña + un
click de periodo + una lectura estable — ampliarlo a todo el resto de mercados dispararía el tiempo de
escaneo por partido para un beneficio marginal decreciente.

`_fetch_match` no distingue deporte al recorrer estos dos mercados (mismo código para todos), pero el
sub-filtro de periodo no está disponible por igual en todos - verificado en vivo el 2026-09-17 contra un
partido real de cada uno:

- **`1X2_HT`**: funciona con datos reales y distintos del partido completo en fútbol, balonmano, béisbol (ahí
  es en realidad "primeras 5 entradas" - "first 5 innings", el mercado estándar de béisbol equivalente a un
  1er tiempo, pero mismo botón/mecanismo) y fútbol americano. **Baloncesto no**: ni "1X2" ni "Local/Visitante"
  ofrecen ningún sub-filtro de periodo ahí (el único que aparece es "Final del partido incluyendo prórroga")
  - los cuartos solo existen dentro del acordeón "Más/Menos de", un mecanismo distinto (periodo + acordeón)
  que no está implementado.
- **`BTTS_HT`**: solo fútbol. Balonmano y béisbol no tienen pestaña BTTS en absoluto. Fútbol americano sí
  tiene la pestaña BTTS, pero verificado en vivo que esa pestaña en concreto no tiene sub-filtro de periodo.

`HALF_TIME_SPORT_EXCLUSIONS` en `providers/cuotasahora.py` excluye explícitamente estas combinaciones sin
soporte (en vez de dejarlas fallar en silencio como DNB/OE) para no gastar tiempo de escaneo en clicks que
nunca van a tener éxito.

**Fuera de alcance a propósito**: tiros/córners/tarjetas **en los comparadores** (CuotasAhora y BetExplorer no
los ofrecen pre-partido, verificado en ambos) — pero sí existen pre-partido en las casas de la plataforma
Altenar, que se leen aparte con `providers/altenar.py` (ver sección "Casas sobre Altenar" más abajo),
"Marcador correcto" (conjuntos de resultados que
no siempre coinciden entre casas, mismo tipo de riesgo de falso positivo que ya causó el bug descrito más
abajo) y "Descanso/Final" (acordeón de 9 combinaciones con poca cobertura, ver `EXTRA_MARKET_TABS`).

### Competiciones y deportes soportados

Además de LaLiga y Champions League, `providers/cuotasahora.py` cubre (verificado en vivo el 2026-09-16 y
ampliado el 2026-09-17):

- **Fútbol**: Premier League, Serie A, Bundesliga, Ligue 1, Europa League, LaLiga2 (LaLiga Hypermotion),
  Copa del Rey, Eredivisie, Liga Portugal, Championship (2ª inglesa), MLS, Süper Lig (Turquía), Jupiler Pro
  League (Bélgica), Brasileirão (Serie A Betano), Liga MX, Liga Profesional Argentina, Premiership
  (Escocia), Conference League, Copa Libertadores, Copa Sudamericana, Bundesliga austríaca, Super League
  suiza, Superliga danesa, Ekstraklasa polaca, Eliteserien noruega, Allsvenskan sueca, HNL croata y Chance
  Liga checa (el slug de URL sigue siendo `fortuna-liga`, nombre anterior de la competición). Se comprobó
  también la Saudi Pro League (dos veces, en rondas distintas), pero sin próximos partidos anunciados
  ninguna de las dos veces (liga entre jornadas, no un problema de URL) — no se añadió por ahora. La Super
  League griega se probó con dos slugs de URL distintos (`super-league-1` y `super-league`), ambos
  devolvieron 404 — no se insistió más, slug correcto pendiente de encontrar. Rugby se volvió a comprobar
  (tercera vez, distintos días/horas) y sigue sin partidos programados en el momento de cada comprobación.
- **Baloncesto**: Liga Endesa/ACB, EuroLeague, NBA y EuroCup.
- **Tenis**: en vez de una URL de "liga" fija como fútbol/baloncesto (los torneos ATP/WTA rotan cada semana,
  no hay competición estable todo el año), apunta al hub general `/tennis/`, que ya lista los partidos del
  día de todos los torneos activos.
- **Balonmano** (deporte nuevo, 2026-09-17): Champions League masculina de la EHF — se eligió por encima de
  cualquier liga doméstica por tener mejor cobertura de casas (12 en la comprobación en vivo). Misma familia
  de pestañas de mercado que fútbol (1X2 con empate, DC, y detrás de "Más": DNB/OE/Descanso-Final, más
  Más/Menos de + hándicap asiático/europeo en acordeón), salvo "Ambos equipos marcan" (BTTS): no existe como
  pestaña para este deporte, así que simplemente no se genera ese `market_type` (fallo silencioso, no rompe
  el resto del escaneo).
- **Béisbol** (deporte nuevo, 2026-09-17): MLB. Igual que baloncesto, la tabla por defecto no tiene empate
  (`"1"`/`"2"` en vez de `"1"`/`"X"`/`"2"`) ni pestañas de BTTS/DC. Se descubrió aquí un problema aparte al
  verificar en vivo: el listado de partidos del día mezcla partidos ya en juego (URL con `/inplay-odds/`,
  visto con varios partidos de la KBO coreana en curso) junto a los de después — `_collect_match_urls` ahora
  descarta explícitamente cualquier href con `inplay-odds`, ya que este sistema es solo pre-partido a
  propósito. Esto corrige el mismo riesgo (aunque nunca observado en la práctica) para el resto de deportes,
  no solo béisbol.
- **Fútbol americano** (deporte nuevo, 2026-09-17): NFL. Sin empate como baloncesto/béisbol, pero a
  diferencia de esos dos sí tiene "Ambos equipos marcan" (BTTS) como pestaña directa. Clave
  `"americano_nfl"` (no `"futbol_americano_nfl"`) a propósito: el deporte real de cada clave se deriva con
  `sport_key.split("_", 1)[0]`, así que un prefijo `"futbol_"` aquí la fusionaría por error con el fútbol
  normal en el motor de arbitraje — hay un test (`test_every_league_key_derives_a_known_sport`) que evita
  reintroducir ese error con una clave nueva mal nombrada.

**Deportes explorados y descartados (2026-09-17)**: antes de añadir cada deporte se comprueba en vivo que
tenga partidos reales y estructura de mercado compatible — estos no pasaron el filtro:

- **Rugby**: solo 2 partidos disponibles (Pro D2 francés y NPC neozelandés), y la mayoría de casas de esos
  partidos eran offshore/cripto sin licencia (fuera de `ALLOWED_BOOKMAKERS`). Cobertura insuficiente hoy, no
  necesariamente un problema estructural — revisar de nuevo más adelante.
- **Dardos, tenis de mesa, MMA, cricket**: sin partidos programados para hoy/mañana en el momento de la
  comprobación (probablemente estacional/por calendario de torneos, MMA en particular solo tiene eventos los
  fines de semana). Mismo motivo: no descartados por estructura, solo sin partidos que verificar ese día.
- **eSports**: el único descarte por motivo técnico real. Las páginas de partido usan enrutado de SPA basado
  en el fragmento de la URL (`#hash`) que **solo resuelve navegando dentro de la página** (clic en el enlace
  del listado); una navegación completa directa a esa misma URL con hash (que es como scrapea
  `_fetch_match`, vía `page.goto()`) se queda en una pantalla placeholder sin tabla ("Select a match from the
  listings..."), confirmado en vivo comparando ambas vías de navegación en el mismo partido. Añadir este
  deporte exigiría un mecanismo de scraping distinto (navegar una vez al listado y clicar cada partido en vez
  de navegar directo a cada URL), no solo sumar una entrada a `DEFAULT_LEAGUE_URLS` — no implementado.
- **Voleibol, hockey sobre hielo**: comprobados dos veces (dos sesiones distintas el mismo día), también sin
  partidos disponibles ninguna de las dos veces — hockey probablemente por calendario (la NHL no empieza
  pretemporada hasta unos días después de la fecha de verificación).

Todo esto se añadió **solo en `providers/cuotasahora.py`**, no en Sportium/Betfair/Winamax, por el mismo
motivo que ya se documentó para la Champions League: `engine/team_aliases.py` solo tiene curados los 20
equipos de LaLiga, y el fallback de similitud de texto genérica es precisamente lo que causó los falsos
positivos del 30-40% descritos más abajo — sumar una liga o deporte nuevo a más de un proveedor sin antes
ampliar esa tabla de alias arriesga reintroducir ese mismo bug. Como CuotasAhora ya agrega varias casas en su
propia tabla por partido, no necesita cruzar el evento con otro proveedor para detectar arbitraje dentro de
esas casas, así que es seguro sumar ligas/deportes ahí en solitario. Siguiente paso natural si se quiere esta
misma cobertura también en Sportium/Betfair/Winamax: ampliar `team_aliases.py` con los equipos relevantes (y
verificar en vivo la estructura DOM de cada casa para baloncesto/tenis) antes de tocar sus
`competition_urls` — no hecho todavía.

`CuotasAhoraProvider` generaliza el mecanismo de fútbol a baloncesto/tenis/balonmano/béisbol/fútbol americano
vía `SPORT_URL_SEGMENT` (mapea `"futbol"/"baloncesto"/"tenis"/"balonmano"/"beisbol"/"americano"` al segmento
de URL real de cuotasahora.com). Para los nombres de equipo usa
el `<title>` de cada página de partido (patrón fijo "Cuotas de Equipo A - Equipo B, pronósticos..."), no el
`<h1>`: el selector CSS usado originalmente (`a.min-w-0.self-center.truncate`) dejó de existir en el DOM
actual del sitio, y el `<h1>` resultó no ser fiable en una sesión de Playwright sin cookies (algunos
partidos devuelven un `<h1>` largo tipo SEO en vez del nombre limpio de los equipos) — detectado y
corregido en el mismo cambio del 2026-09-16 que añadió las ligas/deportes nuevos.

**Nota de rendimiento**: escanear todas estas competiciones (~11 nuevas, cada una con varios partidos y hasta
3 pestañas en acordeón — Más/Menos de, Hándicap asiático, Hándicap europeo — más 4 pestañas de tabla plana)
alarga bastante un ciclo de escaneo frente a solo LaLiga+Champions. La producción real corre vía
`scripts/local_scan.ps1` (Programador de tareas de Windows), no en un bucle de 60s, así que hay margen — pero
conviene revisar `logs/local_scan.log` tras el primer despliegue y, si el ciclo tarda demasiado, reducir
`ACCORDION_MAX_LINES` en `providers/cuotasahora.py` o separar las competiciones nuevas en una tarea de menor
frecuencia.

Detalle completo de cada bloqueo (qué se probó, por qué falló, posibilidades para arreglarlo) y el
trabajo pendiente sobre scraping: ver [checklist.md](checklist.md).

### Segundo comparador: BetExplorer.com (`providers/betexplorer.py`, nuevo 2026-09-17)

Además de CuotasAhora (versión española de OddsPortal), se añadió **BetExplorer.com** como segunda fuente
independiente: empresa distinta, mismo concepto (agrega cuotas de muchas casas DGOJ en una tabla por
partido), verificado en vivo con datos reales, no en teoría.

Diferencias técnicas con CuotasAhora que lo hacen más simple de scrapear:
- Cada pestaña de mercado es una `<table>` HTML normal con `<thead>`/`<tbody>` (CuotasAhora usa divs propios
  sin tabla semántica), así que no hace falta la lógica de extracción a medida de `_EXTRACT_ODDS_TABLE_JS`.
- Para "Más/Menos de" (y también Hándicap asiático, aún no implementado aquí) **todas las líneas ya están
  en el DOM de golpe** (`<table id="sortable-N">`, una por línea), así que no hace falta clicar cada línea
  ni limitar cuántas se leen (`ACCORDION_MAX_LINES` en CuotasAhora existe justo para evitar ese coste, aquí
  no se necesita: el smoke test en vivo extrajo 20 líneas de Más/Menos de de un único partido, de golpe).
- Los nombres de resultado ("1"/"X"/"2", "Yes"/"No", "1X"/"12"/"X2") coinciden carácter a carácter con los
  que ya usa CuotasAhora - verificado en vivo a propósito, para que ambos proveedores puedan fusionar
  correctamente sus outcomes cuando cubren el mismo partido.

Arranca deliberadamente pequeño, mismo criterio que CuotasAhora en su día: solo LaLiga y Champions League
(claves `"futbol"`/`"futbol_champions"`, compartidas con el resto de proveedores). Mercados: 1X2, DNB, DC,
BTTS y Más/Menos de (todas las líneas). Hándicap asiático/europeo quedan pendientes para una siguiente
ronda, no implementados todavía.

**Dos bugs reales encontrados y corregidos en vivo antes de dar el proveedor por bueno** (no en teoría):
- La detección de "partido ya empezado" comprobaba si aparecía el patrón de fecha/hora de inicio en el
  texto de la página - pero esa fecha **sigue apareciendo aunque el partido ya vaya por el minuto 73**
  (verificado en vivo con un partido real en juego). Se cambió a comprobar el elemento
  `.list-details__item__score` (dígitos = partido ya en juego o finalizado, ":" vacío = pendiente).
- El cambio de pestaña por texto visible (`a:text-is("Both Teams To Score")`) funcionaba a mano en
  navegador pero fallaba con timeout en Playwright headless - probablemente un layout de pestañas distinto
  según ancho de viewport (las clases CSS incluyen "Mobile" en el nombre). Se cambió a seleccionar por el
  código interno del `onclick` del sitio (`match_change_tab(matchId, 'bts', ...)`), independiente del
  texto/layout visible.

**Consideración de diseño importante**: al cubrir las mismas ligas que CuotasAhora, sus mercados pueden
fusionarse en `engine/matching.py` (`group_by_event`) si el motor de arbitraje los cruza por evento. En
LaLiga es seguro y positivo (los 20 equipos están en `engine/team_aliases.py`, más casas cruzadas = mejor
detección). En Champions League no hay alias curados, así que el cruce cae al respaldo de similitud de
texto genérica (umbral 0.85) - el mismo riesgo que CuotasAhora ya asumía en solitario ahí, no uno nuevo
introducido por este proveedor, pero con algo más de superficie al haber ahora dos fuentes en esa
competición. Antes de ampliar BetExplorer a más ligas sin alias curados, tenerlo en cuenta.

### Casas sobre Altenar: Jokerbet, Pastón y Betway (`providers/altenar.py`, nuevo 2026-09-20)

Investigando cómo añadir Jokerbet (pedida explícitamente) se descubrió que su web de apuestas es la
plataforma B2B **Altenar** (widget en Shadow DOM con clases CSS con hash, inviable de scrapear por DOM). Pero
ese widget consume una **API JSON pública sin autenticación**
(`sb2frontend-altenar2.biahosted.com/api/widget/...`, parámetro `integration=<casa>`), así que el proveedor
usa `httpx` directamente, **sin navegador** (~20 s para 180 partidos y 19.000 mercados de las 3 casas, frente
a minutos con Playwright). Sondeadas ~30 casas por nombre de integración: solo respondieron **Jokerbet,
Pastón y Betway** (las demás devolvieron 400; el nombre de integración de otras casas puede ser distinto).

Licencias DGOJ: Jokerbet = VERAMATIC ONLINE, S.A. (comprobado en ordenacionjuego.es el 2026-09-20), Pastón =
EUROAPUESTAS ONLINE (2026-09-16), Betway ya estaba verificada. Añadidas a `docs/app.js`.

**Qué aporta y por qué importa**: estas tres casas ofrecen pre-partido **córners, tarjetas, fueras de juego,
tiros, faltas, hándicaps y mercados por mitad** (verificado con el mismo partido en las tres: 36/43/53
mercados de córners y 20/28/38 de tarjetas), justo lo que ninguno de los dos comparadores tiene. Al ser tres
casas distintas sobre la misma plataforma y los mismos IDs de evento, sus precios en estos mercados se
pueden cruzar entre sí (y con los comparadores en los mercados comunes: 1X2, Más/Menos, Ambos marcan,
Hándicap asiático, Impar/Par...).

Detalles de diseño (todos verificados en vivo):
- Los mercados se identifican por `typeId` (global en Altenar, independiente del idioma), no por texto.
  Solo se emiten mercados de resultados **excluyentes y exhaustivos** (lo que asume `engine/arbitrage.py`);
  quedan fuera doble oportunidad, marcador exacto, escalas, combinadas y mercados de jugador.
- Los resultados con equipo se identifican por `competitorId`, no por texto: Betway los llama "1"/"2",
  Jokerbet y Pastón usan el nombre del equipo (y Pastón "X" / "Ambos Marcan: Si"). Sin esto se perdían
  silenciosamente los mercados principales de dos de las tres casas (bug real encontrado al comparar).
- Cada mercado aparece dos veces (vista normal e `isBB` "Crear apuesta"): se deduplica por `id`.
- Solo `oddStatus == 0` (disponible) y cuotas redondeadas a 2 decimales como la web (Altenar devuelve 4).
- El nombre del evento se fija una vez por partido para las tres casas (cada una nombra distinto a los
  equipos: "Valencia CF"/"Valencia"), así cruzan exactamente sin depender de `team_aliases.py`.
- Solo se piden detalles de partidos listados por ≥2 casas y dentro de `ALTENAR_HORIZON_HOURS` (48 por
  defecto; cada partido cuesta ~2 MB descomprimidos por casa). Solo fútbol de momento.
- Líneas de cuarto (2.25, -1.75...) se expresan como "2/2.5", "-2/-2.5" (igual que BetExplorer) y el
  hándicap va siempre desde el local (`AH_-0.5` = local -0.5), **verificado contra BetExplorer**: mismas
  cuotas y mismo lado, así que no se emparejan apuestas opuestas al fusionar fuentes.

**Cuidado con córners y tarjetas**: cada casa liquida estos mercados con sus propias reglas (cómo puntúa una
roja, córners anulados por VAR...). Al ser todas Altenar lo normal es que coincidan, pero **léelas en las
condiciones de cada casa antes de apostar dinero real** a una surebet de estos mercados. Con las 3 casas
compartiendo feed los precios son casi idénticos, así que es esperable que surjan pocas: en la primera
ejecución en vivo (11.092 mercados comparados) el mejor margen fue -4,05%, ninguna surebet.

#### Comprobación cruzada de cuotas entre fuentes (2026-09-20) y defensa anti-cuotas-desfasadas

Se compararon las mismas cuotas entre fuentes para el mismo partido y minuto:
- Espanyol-Elche (LaLiga) y Arsenal-Lille (Champions): CuotasAhora y BetExplorer coinciden **exactamente**
  en las 17 comparaciones casa por casa (comparten incluso el ID de evento interno).
- Valencia-Real Sociedad, 35-45 min antes del partido (con las alineaciones moviendo cuotas): Más/Menos
  2.5 y Hándicap -0.5 idénticos en BetExplorer y CuotasAhora, pero el **1X2 divergía** entre las tres
  fuentes. Paf, a la vez: 2.80/3.25/2.55 en su propia API (Kambi, 18:25:55), 2.60/3.25/2.75 en BetExplorer
  (18:26:11) y 2.88/3.30/2.45 en CuotasAhora (18:18). Betway: 2.67/3.33/2.67 en su API (Altenar) frente a
  2.88/3.25/2.40 en CuotasAhora. Conclusión prudente: **no se puede afirmar cuál comparador va atrasado**
  (las cuotas se movían), pero sí que **en la hora previa al partido los comparadores pueden diferir de las
  APIs directas de las casas hasta ~7% en el 1X2**. Las APIs directas (Altenar, Kambi) son la referencia
  fiable; una surebet que solo salga de comparadores cerca del inicio del partido merece desconfianza.

Una cuota vieja más alta cruzada con una fresca fabrica surebets falsas, así que `best_odds_per_outcome`
(`engine/matching.py`) ahora se queda con la cuota **más baja** cuando la misma casa aparece con el mismo
resultado desde varios proveedores (p.ej. Betway vía CuotasAhora y vía Altenar). Es conservador: una surebet
real lo sigue siendo con la cuota menor. `storage/db.py::export_snapshot` limita además el `data.json` del
panel a las 3.000 comparaciones con mayor margen (la base de datos sí guarda todas).

### Casas sobre Kambi: Paf y LeoVegas (`providers/kambi.py`, nuevo 2026-09-20)

Al comprobar qué plataforma usa cada casa de tu lista (buscando `altenar`/`kambi` en el HTML de sus webs) salió
que **LeoVegas, Paf y Speedybet usan Kambi**, la otra gran plataforma B2B de sportsbook, con una API pública
de ofertas sin autenticación (`eu-offering-api.kambicdn.com/offering/v2018/<operador>/...`, la misma que
consume el front de cada casa). Operadores que responden: `pafes` (Paf) y `leoes` (LeoVegas).

- Verificado en vivo con el mismo partido: ~458 ofertas y 102 criterios pre-partido por casa, incluyendo
  córners (totales, por equipo, por mitad, hándicap), tarjetas, faltas, rojas y mercados por mitad.
- Licencia DGOJ: Paf ya verificada; **LeoVegas comprobada en ordenacionjuego.es el 2026-09-20** (LEOESP,
  S.A. / Leovegas Gaming PLC, apuestas deportivas). Añadida a `docs/app.js`.
- Los mercados se reconocen por `criterion.englishLabel` + `betOfferType` (independiente del idioma), con
  los **mismos prefijos de `market_type` que Altenar y los comparadores** (`1X2`, `1X2_HT`, `DNB`, `BTTS`,
  `OU_<línea>`, `AH_<línea>`, `CORNERS_OU_<línea>`, `CARDS_OU_<línea>`...) para que crucen entre plataformas.
  Cuotas y líneas vienen en milésimas (1910 = 1,91). "Total asiático" solo aporta las líneas que el "Total"
  normal no tiene (las de cuarto). Una oferta con algún resultado suspendido se descarta entera.
- Kambi **limita las peticiones** (HTTP 429) y hubo cortes de conexión puntuales con varias en paralelo: se
  usan 2 hilos y se reintenta con espera creciente. ~44 s para 129 partidos y 7.000 mercados.
- Los IDs de evento de Kambi no coinciden con los de Altenar, así que el cruce entre plataformas depende del
  motor (`engine/matching.py`: alias + similitud ≥ 0,85). Verificado en vivo: **987 grupos con casas de ambas
  plataformas** (p.ej. "AC Milán vs. Lecce", ligas centroamericanas...). Un partido cuyos nombres difieran
  demasiado entre plataformas simplemente no cruza (fallo seguro: se pierde la oportunidad, no se inventa).
- Primera ejecución conjunta Altenar+Kambi (~27.500 mercados, 13.600 grupos): mejor margen cruzado
  **-0,19%** (Más/Menos 10,5 córners de un partido costarricense, betway Over 2,55 + paf Under 1,64), ninguna
  surebet positiva y ninguna cifra absurda. Es el tipo de mercado donde es más plausible que aparezcan.

**Rendimiento del motor**: con esta cantidad de mercados `group_by_event` (`engine/matching.py`) pasó a ser
el cuello de botella: **110 s por ciclo**. Se indexó por (deporte, mercado) y se memoizaron las funciones
puras de comparación de nombres: **4,5 s**, mismos resultados (tests en verde).

### Control de calidad de las surebets (`engine/quality.py`, nuevo 2026-09-20)

Inspirado en cómo se defienden los servicios profesionales (BetBurger: filtro de edad/retraso y rango de
margen; RebelBetting: importes "naturales" para que las casas tarden más en limitar la cuenta). Antes de
avisar, cada candidata pasa por estos controles:

- **Origen y frescura de cada cuota**: `Outcome.source` (proveedor) y `Outcome.fetched_at` los rellena
  `engine/scan.py` justo tras el fetch. Fuentes *directas* (Altenar, Kambi, Sportium, Betfair, Winamax) vs
  *comparadores* (CuotasAhora, BetExplorer, que pueden ir hasta ~7 % desfasados en la hora previa al partido).
- **Fiabilidad** `alta` (todas las cuotas directas) / `media` (alguna de comparador) / `baja` (solo
  comparadores, cuotas leídas con >10 min de diferencia, o comparador cerca del inicio del partido).
- **Confirmación entre ciclos** (`CONFIRM_CYCLES`, 2 por defecto): solo se avisa por Telegram y se guarda en el
  histórico cuando la surebet aparece en escaneos seguidos (equivale al filtro de "edad del arb"). Con un escaneo
  cada ~5 min añade ~5 min de latencia a cambio de filtrar cuotas que parpadean. `1` = avisar a la primera.
- **Errores de datos descartados** (dejan de contar como surebet, pero siguen visibles en el panel como
  "Descartada" con su motivo): `mercado_incompleto` (falta un resultado del mercado, p.ej. un 1X2 sin empate o un
  BTTS con una sola pata: suma de probabilidades <1 sin ser arbitraje real), `una_sola_casa` y `margen_absurdo`
  (> `MAX_MARGIN`, 25 %). El estado guardado antes de este cambio tenía "surebets" del 16-61 % que eran justo esto
  (sobre todo mercados incompletos, que ahora se descartan por su propio motivo sea cual sea el margen).
- **Márgenes muy altos (15-25 %) se verifican, no se descartan** (`VERIFY_MARGIN`..`MAX_MARGIN`): pueden ser reales.
  Se marcan `margen_a_verificar` y, en el mismo escaneo, `engine/scan.py::_verify_high_margins` vuelve a leer las
  fuentes directas y baratas (`fast_recheck`: Altenar y Kambi, sin navegador; ~70 s, solo si hay candidatas). Si todas
  las patas de la candidata vienen de esas fuentes y sigue siendo surebet con la lectura fresca queda **verificada**
  (se avisa enseguida, sin esperar a `CONFIRM_CYCLES`); si la lectura fresca ya no la confirma, desaparece. Si alguna
  pata viene de un comparador (releerlo cuesta minutos de navegador) queda **en verificación**: visible en el panel
  y solo se avisa tras `VERIFY_CYCLES` (3) escaneos seguidos. La verificación no comprueba las cuotas en la propia
  casa: confirma que no eran un parpadeo, así que la comprobación final en la web de la casa sigue siendo tuya.
- **Avisos** (no descartan): `margen_alto` (> `WARN_MARGIN`, 5 %), `solo_comparador`, `cerca_inicio` (<2 h con
  alguna pata de comparador) y `cuotas_desfasadas`. Salen en el aviso de Telegram y en la columna Fiabilidad.
- **Hora de inicio** (`Market.start_time`): la rellenan Altenar y Kambi (los comparadores no la exponen todavía).
  `engine/matching.py` no fusiona dos mercados con hora conocida que difieran más de 6 h (ida/vuelta, liga y
  copa con los mismos equipos), y el aviso/panel muestran cuándo empieza.
- **Importes redondeados** (`ROUND_STEP`, 5 € por defecto; `0` = céntimos exactos): `engine/arbitrage.py::round_stakes`
  prueba el múltiplo inferior y superior de cada pata y se queda con la combinación de mayor rentabilidad que sigue
  garantizando beneficio (el beneficio mostrado es el peor caso real con los importes ya redondeados). Si con 5 €
  no queda beneficio, prueba con 1 €. La calculadora del panel hace lo mismo.
- **Panel** (`docs/`): columnas Inicio, Fiabilidad (con los avisos) y Edad (tiempo continuo como surebet);
  filtros por deporte, fiabilidad, "empieza en < N h", rango de margen y orden por margen / inicio / antigüedad
  (se recuerdan en el navegador). Las filas descartadas van siempre al final y no cuentan como mejor margen.

Las variables (`CONFIRM_CYCLES`, `ROUND_STEP`, `WARN_MARGIN`, `VERIFY_MARGIN`, `MAX_MARGIN`, `VERIFY_CYCLES`) están
en `.env.example`.
`storage/db.py::init_db` migra con `ALTER TABLE` la tabla `comparisons` de bases de datos ya existentes.

**Decisión de producto**: no se implementa value betting (apostar a cuotas por encima del precio justo); el
sistema es solo de surebets.

## Aviso legal

El arbitraje deportivo no es ilegal en España (Ley 13/2011), pero cada casa de apuestas puede limitar o cerrar
cuentas por sus propios términos y condiciones. El scraping debe hacerse de forma moderada y revisando los
términos de servicio de cada operador. Ver el documento base para más detalle.
