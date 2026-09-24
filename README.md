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

## Panel web en tu PC (y verlo desde el móvil)

El panel es la carpeta `docs/` (HTML+JS estático que lee `docs/data.json`, que regenera el escaneo local).

```powershell
scripts\start_local_web.ps1          # solo en este PC:  http://localhost:8000
scripts\start_local_web.ps1 -Lan     # también desde el móvil (imprime las URLs)
```

- **Misma WiFi**: abre `http://<IP-del-PC>:8000/` en el móvil. Requiere una sola vez, como administrador,
  la regla de firewall que el propio script te imprime. Si usas ProtonVPN, activa "permitir LAN" en su configuración.
- **Desde cualquier sitio**: instala [Tailscale](https://tailscale.com) (gratis) en el PC y el móvil, con la misma cuenta,
  y abre la URL `100.x.x.x:8000` que imprime el script. Es una red privada: no queda nada expuesto a internet.

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
| **Sportium** | ✅ Funciona (`providers/sportium.py`) | Playwright headless normal, sin trucos. 1X2, Más/Menos (Goles Totales, línea variable por partido), Doble Oportunidad, Ambos Marcan y Resultado al descanso en vivo verificados (2026-09-22). |
| **Betfair** | ⚠️ Solo 1X2, a propósito (`providers/betfair.py`) | Playwright headless normal. 1X2 funciona. El Más/Menos de 2,5 (y los intentos de ampliar a Doble Oportunidad/Ambos Marcan/Córners) están implementados pero **desactivados**: el cambio de mercado dispara el challenge "Verificación de seguridad" de Cloudflare — verificado en vivo el 2026-09-22, persiste tras 5 min de espera, no se ha intentado evitarlo. Ver detalle abajo. |
| **Winamax** | ✅ Funciona (`providers/winamax.py`) | Por el socket de su propia web (socket.io), abierto desde un navegador: 23 competiciones y ~100 mercados por partido (1X2, DNB, doble oportunidad, ambos marcan, Más/Menos con muchas líneas y por equipo, hándicap asiático, Par/Impar, primer/último gol, todo también por mitades). Sin córners ni tarjetas pre-partido (comprobado sobre 388 tipos de mercado). Una petición HTTP suelta recibe 403; la web completa no siempre conecta su cliente, por eso se habla el socket directamente. |
| **bwin** (nuevo 2026-09-21) | ✅ Funciona (`providers/bwin.py`) | API JSON de su propio front (`cds-api`), leída desde el navegador con la página cargada (HTTP suelto = 403). Fuente **directa** con cientos de mercados por partido, incluidos córners, tarjetas, hándicap asiático y mercados por mitad. Su "Resultado VA (+2)" (pago anticipado) NO se trata como 1X2. |
| **CuotasAhora.com** (comparador) | ✅ Funciona (`providers/cuotasahora.py`) | Playwright headless. No es una casa, es un comparador (versión española de OddsPortal) que agrega 1X2 de ~14 casas por partido en una sola tabla HTML. Ver detalle abajo — es la vía por la que se desbloquean, indirectamente, bet365/bwin/Codere/Luckia/William Hill. |
| **BetExplorer.com** (comparador, nuevo 2026-09-17) | ✅ Funciona (`providers/betexplorer.py`) | Playwright headless. Segundo comparador, empresa distinta a CuotasAhora/OddsPortal. Mismas casas DGOJ, tablas HTML semánticas (más simples de leer que CuotasAhora). Ver detalle abajo. |
| **Jokerbet, Pastón, Betway** (plataforma Altenar, nuevo 2026-09-20) | ✅ Funciona (`providers/altenar.py`) | API JSON pública de su widget, sin navegador. Córners, tarjetas, hándicaps y mercados por mitad pre-partido, que los comparadores no tienen. Ver detalle abajo. |
| **Paf, LeoVegas** (plataforma Kambi, nuevo 2026-09-20) | ✅ Funciona (`providers/kambi.py`) | API pública de ofertas de Kambi, sin navegador. Fuente **directa** de la casa (no comparador): mismos mercados extra que Altenar (córners, tarjetas, faltas, hándicaps, por mitad) pero otra plataforma y otros precios, lo que permite arbitraje entre plataformas. Ver detalle abajo. |
| **PokerStars** (nuevo 2026-09-23) | ✅ Funciona (`providers/pokerstars.py`) | Playwright headless normal, DOM (`/sports/futbol/1/matches/`, atributos `data-testid` estables, no clases con hash). Solo 1X2 por ahora. Su API JSON propia (parece tecnología Betfair) está detrás de Akamai Bot Manager — un `fetch()` a mano dentro de la página ya da 403, mismo patrón que Kirolbet — por eso se lee el DOM en vez de hablarla directo. Plataforma propia, no Altenar/Kambi/Sportify. |
| **Speedybet** | ⚠️ Solo vía comparadores | Su web dice usar Kambi (mismo grupo que Paf) pero no se encontró su código de operador (probados ~15 nombres, varios devolvieron 429 por límite de peticiones, no concluyente). Sigue entrando vía CuotasAhora/BetExplorer. |
| **William Hill** (nuevo 2026-09-23) | ✅ Funciona (`providers/williamhill.py`) | API JSON pública de su plataforma OpenBet, sin navegador ni cookies (funciona igual con o sin sesión). El bloqueo de IP de datacenter/VPN ("Data Centre block") es solo de la web `sports.williamhill.es`, no de esta API — probado en vivo desde IP residencial (carga bien) y desde este sandbox (API responde 200 igual, la web sigue bloqueada). Solo 1X2: pedir el mercado por su nombre de la web ("Ganador del partido") da la promo "2 Up" (paga como ganador con 2 goles de ventaja), no cuotas normales — el 1X2 real vive bajo el grupo "Ganador del Partido - Cuotas mejoradas", mismo caso que el "Resultado VA (+2)" de bwin. |
| **bet365, bwin, Codere, Luckia** | ⚠️ Indirecto, vía CuotasAhora.com / BetExplorer.com | Bloqueadas para scraping directo (ver causas abajo), pero sus cuotas 1X2 llegan igualmente a través de ambos comparadores. bet365 confirmado en vivo el 2026-09-23: sigue con Cloudflare incluso desde Playwright headless real y desde la IP residencial del usuario (no es solo IP de datacenter, como sí lo era William Hill). |
| **888sport, Betway, Retabet, Paf.es, Speedybet.es, Versus.es, 1xBet.es** | ✅ Vía CuotasAhora.com / BetExplorer.com | No probadas directamente, cubiertas de golpe a través de los comparadores. |
| **Kirolbet** | ⚠️ Implementado pero bloqueado (`providers/kirolbet.py`) | Akamai Bot Manager. Ver detalle abajo. |
| **Betsson** | ❌ Bloqueado | API antifraude propia. Ver detalle abajo. |
| **Suertia (OlyBet)** | ❌ Bloqueado a nivel de red | "Access Denied" del proveedor. Ver detalle abajo. |
| **Marca Apuestas** (nuevo 2026-09-23) | ✅ Funciona (`providers/marcaapuestas.py`) | El bloqueo Cloudflare/403 antiguo ya no aplica: la casa cambió de frontend. Confirmado con Playwright headless real, sin trucos (status 200, sin ningún reto). Resultó ser **el mismo framework "ta-" que Sportium** (mismas clases CSS y mismos códigos internos de mercado BTSC/H1RS), así que el provider es casi una copia del de Sportium: 1X2, Más/Menos, Ambos Marcan y Resultado al descanso (sin Doble Oportunidad, que esta casa no tiene en su desplegable). Ver `estudio_tecnicas_otros_bots.md`. |
| **Interwetten** | ⚠️ Implementado pero bloqueado (`providers/interwetten.py`) | DOM limpio y parseable (clases semánticas estables, sin CSS-modules), pero Cloudflare devuelve el challenge JS "Just a moment..." a cualquier Playwright headless, confirmado en dos entornos (sandbox de desarrollo y PC de producción del usuario, IP residencial) el 2026-09-22 — no es throttling de sandbox como cuotasahora.com, es un bloqueo real. El navegador interactivo sí carga la página, pero automatizar eso sería evasión de anti-bot: no se hace. |
| **Zebet** (nuevo 2026-09-24) | ✅ Funciona (`providers/zebet.py`) | Playwright headless normal, sin trucos — confirmado en vivo tras descartar que fuera un falso positivo del Browser pane (mismo patrón que Interwetten/Retabet/OlyBet). Plataforma propia del grupo Zeturf (no un B2B conocido). DOM limpio con clases estables (`bet-actor1`/`bet-actorN`/`bet-actor2` para 1/X/2, no por texto); cuotas ya en el HTML servido, no hace falta la conexión SSE que solo empuja partidos en vivo. Solo 1X2 de LaLiga por ahora. |
| **Botemanía** (Pastón, LeoVegas, Yosports ya funcionan vía Altenar/Kambi, ver arriba) | ✅ Funciona vía Kambi (`providers/kambi.py`, tenant `botemaniaes`, nuevo 2026-09-21) | Con licencia DGOJ confirmada (ver abajo). |
| **Betfair Exchange** (nuevo 2026-09-23, `providers/betfair_exchange.py`) | ⚠️ Implementado, **sin verificar en vivo** | API oficial gratuita (Delayed App Key), aparte del scraper DOM de la web de apuestas fijas (`providers/betfair.py`). A diferencia de todo lo demás de esta tabla, no se ha podido probar contra la API real: hace falta una app key + cuenta de Betfair que solo el usuario puede generar (developer.betfair.com). Se salta sola en el escaneo si `BETFAIR_APP_KEY`/`BETFAIR_USERNAME`/`BETFAIR_PASSWORD` no están en `.env`. Ver `estudio_tecnicas_otros_bots.md`. |

✅ **Licencias DGOJ verificadas (2026-09-16)**: se contrastaron a mano las 78 fichas del buscador oficial
de operadores ([ordenacionjuego.es](https://www.ordenacionjuego.es/operadores-juego/operadores-licencia/operadores)).
**Todas** las casas usadas por este sistema (directas + vía CuotasAhora, incluido 1xBet.es) tienen licencia
vigente en España — la sospecha inicial de que 1xBet.es no la tuviera era incorrecta (licencia bajo WAGERFAIR,
S.A.). De paso se confirmó que Paston, Botemanía, Zebet y PokerStars Sports también están licenciadas
(EUROAPUESTAS ONLINE, GAMESYS SPAIN, ZEBETTING Y GAMING, TSG INTERACTIVE respectivamente); las cuatro tienen
ya scraping directo implementado (Altenar, Kambi, `providers/zebet.py` y `providers/pokerstars.py`
respectivamente, Zebet añadido el 2026-09-24). El panel web ([docs/](docs/)) marca en rojo cualquier casa que no esté en esta
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

### Cambios del 2026-09-21 (Betfair, caché de comparadores, filtros y cruce de equipos)

- **Betfair**: la web dejó de marcar cada partido con `-fixture`+`viewCoupon` (0 mercados, "FALLÓ" en todos los
  escaneos). Ahora cada partido es un bloque `-couponContainer` con 2 equipos y sus botones de cuota; el extractor
  usa ese ancla y conserva el antiguo como respaldo. Verificado en vivo: 18 mercados (1X2 y Más/Menos 2,5 de 9 partidos).
- **Caché de comparadores** (`engine/cache.py`): la rotación ya no es uniforme. Cada competición tiene un intervalo de
  refresco según su prioridad (las 6 primeras del listado 2 h, el resto del fútbol 5 h, otros deportes 8 h) y se lee
  primero la más atrasada; antes BetExplorer no llegaba a leerse nunca porque 32 competiciones de CuotasAhora "sin
  leer" iban delante. Una lectura vacía (puerta de edad, limitación del sitio) se reintenta a los 20 min, 40, 80...
  Además CuotasAhora y BetExplorer repiten una vez, con más paciencia, un listado de liga que sale vacío.
- **Filtros** (`providers/filters.py`): Altenar y Kambi descartan el fútbol virtual/e-soccer (en Kambi era el ~58 % de
  los partidos) y el fútbol femenino, usando la categoría/competición/ruta que da la propia casa. Se desactivan con
  `EXCLUDE_ESPORTS=0` / `EXCLUDE_WOMENS_FOOTBALL=0` en `.env`.
- **Cruce de equipos** (`engine/team_aliases.py`, `engine/matching.py`): con partidos reales de Altenar y Kambi a la misma
  hora, solo cruzaban 17 de 37 ("Chievo"/"Chievo Verona", "Dep. Capiata"/"Deportivo Capiata", "Corea del Sur
  Sub-23"/"South Korea Sub-23"...). Ahora hay alias curados para las ligas grandes y un cruce por palabras
  significativas para el resto. Las reglas "sueltas" (versiones abreviadas) solo valen con hora de inicio conocida en
  ambos partidos y a menos de 30 min; los comparadores (sin hora) siguen con cruce estricto. Nunca se juntan nombres
  con marcas distintas (femenino, sub-23, filial, "(Nairo)" de e-soccer). Limitación conocida: la similitud de texto
  heredada sigue juntando algunos pares parecidos ("America"/"América-MG"), que solo se dan con el mismo rival y hora.

**Doble oportunidad** (`DC`, `DC_HT`, `DC_2H`; resultados `1X`/`12`/`X2`): Altenar y Kambi la emiten desde el 2026-09-21, así que cruza con
Winamax, bwin y los comparadores. Altenar identifica cada resultado por el `typeId` de la selección (9/10/11) y no por su texto; Kambi por su
tipo (`OT_ONE_OR_CROSS`...). Jokerbet no ofrece este mercado; las combinadas ("doble oportunidad y ambos marcan"...) no se emiten.

### Intento de scraping directo de más casas (2026-09-21)

Comprobado con un Playwright headless normal (sin técnicas de evasión, que este proyecto no usa):

| Casa | Resultado |
|---|---|
| bet365 | ❌ Cloudflare 403 ("Sorry, you have been blocked"). Además reparte las cuotas por un websocket cifrado. Solo llega vía comparadores. |
| Luckia, 1xBet | ❌ Desafío de Cloudflare ("Just a moment..."). |
| Retabet | ❌ "Error de seguridad" (403). |
| William Hill | ~~❌ Bloquea centros de datos/VPN~~ **Resuelto 2026-09-23**: solo la web (`sports.williamhill.es`), su API JSON no bloquea nada. Ver `providers/williamhill.py`. |
| Codere | ❌ Akamai Bot Manager en la plataforma real de apuestas (`m.apuestas.codere.es`, un subdominio aparte de `www.codere.es` que sí carga bien). "Access Denied" incluso reusando las cookies de sensor de Akamai de `www.codere.es`, probado desde la IP residencial del usuario — mismo nivel que Kirolbet. Solo llega vía comparadores. |
| 888sport, Versus | ⚠️ Cargan, pero no exponen un JSON de cuotas evidente (888sport usa la plataforma "unified client" de safe-iplay; Versus un widget propio). Sin explorar. |
| bwin, Winamax | ✅ Integradas (arriba). |

### Mercados soportados

Además de 1X2, Sportium y Betfair scrapean también over/under de goles (verificado en vivo). Convención de
nombres: `market_type` es `"OU_<línea>"` (p.ej. `"OU_2.5"`) y los outcomes son `"Over"`/`"Under"`. Betfair
tiene la línea 2,5 como opción de menú fija, así que siempre es `OU_2.5`. Sportium sugiere una línea por
partido (normalmente 2,5, pero no siempre — puede ser 3,5 o 4,5 en partidos muy desnivelados), así que su
`market_type` varía por partido; al incluir la línea en el propio `market_type`, `group_by_event` nunca
compara por error una línea con otra. **Winamax** (actualizado 2026-09-21, ver fila de la tabla arriba) va mucho
más allá de 1X2: por el socket de la ficha de cada partido llegan también DNB, doble oportunidad, ambos
equipos marcan, Par/Impar (partido y por equipo), primer/último gol, Más/Menos de (muchas líneas, partido y
por equipo) y hándicap asiático, todo también por mitades — `providers/winamax.py::parse_match_state`, con
tests en `tests/test_winamax_provider.py`. Sin córners ni tarjetas pre-partido (comprobado sobre 388 tipos de
mercado).

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
- **Baloncesto**: Liga Endesa/ACB, EuroLeague, NBA y EuroCup. Desde 2026-09-24 también tienen fuente directa
  en Altenar/Kambi (hándicap, total y par/impar por cuarto y mitad, incl. prórroga) - ver "Baloncesto y tenis
  en Altenar y Kambi" más abajo.
- **Tenis**: en vez de una URL de "liga" fija como fútbol/baloncesto (los torneos ATP/WTA rotan cada semana,
  no hay competición estable todo el año), apunta al hub general `/tennis/`, que ya lista los partidos del
  día de todos los torneos activos. Desde 2026-09-24 también tiene fuente directa en Altenar/Kambi (hándicap
  y total de juegos, hándicap de sets, mercados del primer set).
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

### Cinco casas más sobre Altenar y Kambi (2026-09-21)

Se cruzó la lista oficial de la DGOJ (78 operadores, ordenacionjuego.es) con la plataforma que usa cada casa. Se
añadieron las que respondían con partidos en la API pública de su plataforma, sin más código que su nombre en
`INTEGRATIONS` (`providers/altenar.py`) u `OPERATORS` (`providers/kambi.py`):

| Casa | Plataforma | Código | Partidos ese día | Licencia (registro DGOJ) |
|---|---|---|---|---|
| Betinia | Altenar | `betinia` | 920 | IBERIX GAMING, S.A.U. |
| DAZN Bet | Altenar | `daznbet` | 721 | DZBT DEPORTES, S.A. |
| Yosports | Kambi | `yosportses` | 276 | RANK DIGITAL CEUTA, S.A. |
| Botemanía | Kambi | `botemaniaes` | 161 | GAMESYS SPAIN, S.A. |
| Speedybet (ahora también directa) | Kambi | `pafspeedybetes` | 156 | PAF GAMES, S.A. |

- El código de Speedybet salió del tráfico de su web (`settings-api.kambicdn.com/pafspeedybetes__startup.json`); los
  demás, de probar el nombre en la API. Adivinar códigos de Kambi choca con su límite de peticiones (429): mejor
  mirar el tráfico real de la web de cada casa.
- Con 5 casas Altenar empezó a limitar peticiones (429) y se perdían partidos enteros de alguna casa (DAZN Bet
  desaparecía): `_get_json` ahora reintenta el 429 con espera creciente y se bajó a 3 hilos (28 s por ciclo, 0
  fallos; con 4 hilos eran 83 s y 8 fallos).
- **Ojo**: casas de la misma plataforma tienen precios casi idénticos (Speedybet y Paf, del mismo grupo, dan
  exactamente los mismos ~6.130 mercados). Aportan capacidad para repartir dinero y límites, pero pocas surebets
  entre sí; lo que más aporta es una plataforma distinta.
- **Descartadas en la revisión**: Casino Gran Madrid (Altenar, integración `casinogranmadrid`, pero la API responde
  401: exige un token de sesión), Kirolbet/Interwetten/Casino Barcelona/Efbet/Aupabet (403), Betsson (antifraude),
  Suertia/OlyBet (Access Denied). Los comparadores no muestran ninguna casa extra: solo las que ya usamos más
  Sportium y Winamax (que se leen directas).

#### Bet777 (`providers/bet777.py`, implementada 2026-09-21)

Plataforma propia "Sportify" (dejó SBTech en dic. 2023), con cuotas de **FeedConstruct/SoftConstruct**: una tercera
fuente de precios distinta de Altenar y Kambi, la que más aporta al cruce. Licencia: DIGITAL DISTRIBUTION
MANAGEMENT IBÉRICA, S.A. (bet777.es). Se lee **sin navegador ni autenticación**, con `httpx`, por la misma API que
usa su web (`api.sportify.bet`, parámetro `bookmaker=bet777es`):

- Listado: `GET /echo/v1/events?sport=football&lang=en` -> competiciones -> eventos con `id` (`1-30936492`),
  `teams`, `starts_at` (UTC), `is_live`, `is_suspended`. Solo pre-partido dentro de `BET777_HORIZON_HOURS` (48),
  sin fútbol virtual ni femenino (`providers/filters.py`; el femenino se reconoce por "Women" en la competición).
- Detalle: `GET /echo/v1/markets?event_id=<id>&lang=en` -> ~214 mercados (56 KB, 0,3 s). Los mercados se reconocen
  por `name_untranslated` (inglés) y los resultados por `kind`, y se emiten con los mismos prefijos que Altenar,
  Kambi y los comparadores (`1X2`, `1X2_HT`, `1X2_2H`, `DNB`, `BTTS`, `BTTS_HT`, `OE`, `OU_<línea>`, `OU_HOME_<línea>`,
  `OU_AWAY_<línea>`, `AH_<línea>`, con variantes `_HT`/`_2H`). Cada mercado trae todas sus líneas juntas
  (`Over (2.5)` / `Under (2.5)`): se emparejan por línea, las de cuarto se escriben `2/2.5` (igual que el resto) y
  solo se emiten parejas completas y sin suspender. Cuota = la que muestra la web (2 decimales); `cash_out` sale
  del mercado.
- **Córners y tarjetas, añadido 2026-09-22**: la comprobación original en LaLiga/Premier League dijo que no había
  (esas dos ligas en concreto no traen esos grupos), pero ligas de menor perfil sí — verificado en vivo con 15
  competiciones (Serie B brasileña, Primera A colombiana, Copa Chile, Asian Games...), hasta 280 mercados por
  partido. Nombre con forma `"Corners: [1st/2nd Half ]<sub>"` (la categoría va delante, a diferencia de los
  mercados de goles), reconocida por `_METRIC_RE` en vez de por `_FULL_TIME`/`_HALF`. Se emiten con los mismos
  prefijos que Altenar/Kambi para que crucen entre plataformas: `CORNERS_OU`/`CORNERS_OU_HOME`/`CORNERS_OU_AWAY`
  (con `_HT`/`_2H`), `CORNERS_1X2`(`_HT`), `CORNERS_OE`, `CORNERS_FIRST`/`CORNERS_LAST` (2 resultados, sin
  "ninguno" a diferencia de Altenar — mismo `kind` que Draw No Bet) y los mismos para `CARDS_`. Fuera: "Total Red
  Cards" y "First/Last Yellow Card" (ninguna otra fuente los emite hoy, no podrían cruzar nunca) y los de
  bandas/franjas/"race to" (no son de dos/tres resultados exhaustivos). Sin tiros ni faltas (no aparecieron en
  ninguna de las 15 competiciones comprobadas). Verificado en vivo tras el cambio: 156 mercados de córners/tarjetas
  en 12 de 43 partidos de un ciclo real (antes: 0).
- Sin doble oportunidad, marcador correcto, bandas, combinadas ni hándicap de 3 vías (no son excluyentes y
  exhaustivos, o de jugador).
- Gotchas encontrados en vivo: algunos partidos devuelven `markets` como objeto con claves `"0","1",...` en vez de
  lista (se normaliza); el orden de local/visitante coincide con `teams` (0 partidos con `teams_reversed` de 50).
- Un ciclo: ~43 partidos y ~2.800 mercados en unos 10-15 s (antes de añadir córners/tarjetas: ~2.400); cruza con
  Betway, Paf, bwin y Jokerbet. `fast_recheck = True` (API barata: participa en la verificación de márgenes muy
  altos) y figura en `DIRECT_SOURCES`.
- **Baloncesto y tenis, añadido 2026-09-24**: el mismo endpoint funciona igual con `sport=basketball`/`sport=tennis`
  (verificado en vivo, sin autenticación) y con el mismo vocabulario de `kind` que fútbol (Over/Under, Home/Away,
  Odd/Even), así que la lógica de parseo (`_line_markets`/`_fixed_market`) se reutiliza sin cambios; solo cambia el
  diccionario de nombres reconocidos. Baloncesto: "Match Winner" (2 vías incl. prórroga) -> `ML`; "Points Handicap"
  -> `AH`; "Total Points" (y por equipo) -> `OU`/`OU_HOME`/`OU_AWAY`; "Total Points Odd/Even" -> `OE`; por mitad
  igual con `_HT`/`_2H` (el ganador de mitad se llama "Winner (2-Way)" en esta casa, pero se emite como `DNB_HT`
  para cruzar con Altenar/Kambi); por cuarto (`_Q1".."_Q4`) solo hay hándicap/total/par-impar, sin ganador a 2 ni 3
  vías. Tenis: "Match Winner" -> `ML`; "Games Handicap" -> `AH`; "Total Games" (y por jugador) ->
  `OU`/`OU_HOME`/`OU_AWAY`; "Sets Handicap" -> `SETS_AH`; "Total Sets" -> `SETS_OU`; por primer set (nunca se vio
  "2nd Set" pre-partido) -> `ML_SET1`/`AH_SET1`/`OU_SET1`. Fuera en ambos deportes: "Match Result (Regular Time)"
  de baloncesto (3 vías con empate antes de prórroga, sin pareja en Altenar/Kambi), márgenes de victoria,
  combinados y mercados de jugador.
- La API no está documentada y puede cambiar sin aviso.

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
- **Lectura duplicada (`lectura_duplicada`, descartada)**: si todas las patas (casa, cuota) de una surebet con
  alguna pata de comparador aparecen idénticas en OTRO mercado del mismo partido, el comparador enseñaba la tabla
  de otra pestaña (1X2) al leerla. En el estado del 2026-09-17 el 24 % de las comparaciones compartían casas y cuotas
  exactas con otro mercado (BTTS, BTTS_HT, OU_0 y DC con las cuotas 1/X del 1X2) y 22 de las 28 "surebets" eran eso.
  Como el fallo es sistemático, repetir la lectura varios ciclos no lo detecta; por eso se comprueba la estructura,
  no el margen. El 1X2 nunca se marca (es la tabla original) y AH 0 ≡ DNB no cuenta como duplicado.
- **Filas de comparador imposibles** (`drop_incoherent_rows`, se quitan antes de calcular nada): una casa no puede
  ofrecer todos los resultados de un mercado exhaustivo con probabilidades que sumen menos de 1 (su margen la deja
  siempre por encima). Calibrado con 35.738 filas casa-mercado de todas las fuentes: mediana 1,088, percentil 1 en
  1,047, **ninguna fuente directa por debajo de 0,99** y las 81 filas por debajo de 0,99 eran todas de CuotasAhora
  (`BTTS_HT` y las líneas 0 de `OU`/`AH`, con la tabla de otra pestaña). Umbral `COHERENCE_MIN` = 0,97; solo se
  juzgan filas completas y de comparador (una fila directa <1 sería un error real de la casa) y el doble oportunidad
  queda fuera (sus resultados se solapan). Las 6 "surebets" de `BTTS_HT` del 17-24 % del 2026-09-21 eran esto: las
  6 casas de la tabla sumaban 0,78. El log del ciclo dice cuántas lecturas se quitaron.
- **Cuotas atípicas** (`leg_flags`): una pata cuya cuota es >= 1,25 veces la mediana de lo que pagan las OTRAS casas
  por el mismo resultado y difiere en >= 8 puntos de probabilidad (con al menos 2 casas más como referencia). Sobre
  2.500 patas reales la mediana del ratio es 1,03 y el percentil 99 es 1,25, así que salta ~0,2 %: sobre todo Betway
  en tenis (una cuota de 16,0 frente a una mediana de 2,14) que fabricaba márgenes del 17-33 %. Si la pata viene de un
  **comparador** la surebet se descarta (`cuota_atipica`: no se puede comprobar en el momento y los comparadores tienen
  fallos de lectura documentados); si viene de una fuente **directa** se conserva con el aviso `cuota_destacada`
  (fiabilidad como mucho media): es lo que la casa ofrece de verdad, así que puede ser un error suyo o una
  oportunidad real, y lo decide quien mira la web de la casa.
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

### Escaneo en dos ritmos: rápido (directas) y lento (comparadores) (2026-09-20)

Un ciclo completo con las 38 competiciones de CuotasAhora tarda **horas** (~30 s de navegador por partido, ~600
partidos; medido: solo LaLiga = 8 min). Con la tarea programada cada 5 min y sin solaparse, en la práctica el sistema
publicaba una vez cada varias horas, y las fuentes rápidas (Altenar, Kambi: las de córners y tarjetas) se leían las
últimas, tras los comparadores. Por eso se separó en dos tareas (`scripts/scan_once_action.py --mode ...`):

| Modo | Tarea programada | Qué lee | Cada cuánto | Qué hace |
|---|---|---|---|---|
| `fast` | `SurebetsLocalScan` (`scripts/local_scan.ps1`) | Sportium, Betfair, Winamax, Altenar, Kambi (~1-2 min) + **caché** de los comparadores | 5 min | detecta surebets, avisa, guarda en la base de datos y `docs/data.json`, commitea |
| `slow` | `SurebetsSlowScan` (`scripts/local_slow_scan.ps1`) | CuotasAhora y BetExplorer | 30 min, presupuesto de 20 min | rota por competiciones (la que lleva más tiempo sin leerse primero) y **actualiza la caché**; no avisa, no toca git ni la base de datos |
| `full` | GitHub Actions / manual | todo en un ciclo | — | comportamiento antiguo |

- **La caché** (`engine/cache.py`, `cache/comparator_cache.json`, fuera de git) guarda por (proveedor, competición) los
  mercados leídos, con la hora original de cada cuota. El ciclo rápido la usa a través de `CachedProvider`, así que
  el motor ve la **antigüedad real** de las cuotas de comparador: una surebet que mezcla una cuota directa de ahora
  con una de comparador de hace horas sale marcada `cuotas_desfasadas` (fiabilidad baja). Es honesto: son precios
  que pudieron cambiar. Una lectura vacía de una competición no borra lo que ya había (suele ser carga puntual del
  sitio). Lo cacheado con más de `COMPARATOR_MAX_AGE_HOURS` (8) deja de usarse.
- **Rotación**: el ciclo lento lee como mucho `SLOW_MAX_MATCHES` (12) partidos por competición (los más próximos) y
  se detiene al agotar `SLOW_BUDGET_MINUTES` (20; se comprueba entre competiciones). A ~30 s por partido, una vuelta
  completa a las 38 competiciones lleva unas horas: los comparadores son la fuente más lenta y menos fiable, y las
  APIs directas se leen a ritmo de minutos.
- **Estado de las fuentes**: cada ciclo rápido deja en `docs/data.json` → `settings.sources` los mercados y
  partidos leídos de cada fuente (y, para los comparadores, cuántas competiciones tiene la caché y cuánto de vieja es
  la lectura más antigua). `scripts\status_scan.ps1` lo imprime y marca `SIN DATOS` las fuentes con 0 mercados.
- **Tareas**: `scripts\install_scan_tasks.ps1` crea `SurebetsSlowScan` (deshabilitada, copiando el usuario y los ajustes
  de la rápida); `scripts\start_scan.ps1` enciende y dispara las dos (la lenta primero, para llenar la caché) y
  `scripts\stop_scan.ps1` las apaga y mata también el Python y los Chromium que hubiera en marcha.
- Variables (`.env.example`): `SLOW_BUDGET_MINUTES`, `SLOW_MAX_MATCHES`, `COMPARATOR_MAX_AGE_HOURS`.

### Igualar mercados entre casas: horizonte de Winamax demasiado corto (2026-09-22)

**Contexto**: el usuario pidió retomar el trabajo de igualar la cantidad de mercados entre casas, para que
crucen más y salgan más surebets. Al revisar `docs/data.json` → `settings.sources` de los últimos ciclos en
producción, Winamax llevaba **varios ciclos seguidos dando 0 mercados de 0 partidos**, pese a que
`providers/winamax.py::parse_match_state` ya soporta ~9 tipos de mercado (ver "Mercados soportados" arriba,
cambio del 2026-09-21) — el problema no era de mercados soportados, sino que no se estaba leyendo ningún
partido en absoluto.

**Causa confirmada en vivo** (conectando al socket real, no teórica): `WinamaxProvider` filtraba los partidos
por `WINAMAX_HORIZON_HOURS=36`, y en el momento de la comprobación el partido más próximo de LaLiga estaba a
407 h vista (~17 días), Champions League a 501 h y Premier League a 424 h — un hueco de calendario (compás de
selecciones nacionales) que afecta a la vez a las principales ligas europeas que cubre Winamax. Con un
horizonte de 36 h, cualquier hueco de calendario más largo que eso deja la fuente completamente a cero, a
diferencia de Sportium (sin horizonte, lee lo que muestre el listado) o Betfair/Altenar/Kambi/bwin/bet777 (48 h
por defecto). Incluso ligas no afectadas por selecciones (Liga MX, a 78 h vista) quedaban fuera con 36 h.

**Corrección aplicada**: `WINAMAX_HORIZON_HOURS` sube de 36 a **96** (`.env.example` y valor por defecto en
`providers/winamax.py`) — el doble que el resto del ecosistema, para no dejar la fuente a cero por huecos de
calendario cortos sin dejar de ser "pre-partido cercano". `WINAMAX_MAX_MATCHES` (12) ya limitaba el coste por
competición independientemente del horizonte (`_select` ordena por fecha y corta), así que ampliar el horizonte
no aumenta el tiempo de escaneo. Verificado en vivo tras el cambio: Liga MX pasó de 0 a 2 partidos leídos y 101
mercados (OU, AH, OE, DC, DNB, 1X2, BTTS, primer/último gol) en una sola llamada. Ligas con hueco de calendario
más largo que 96 h (LaLiga, Champions, Premier, en el momento de la comprobación) siguen en 0 hasta que su
próxima jornada entre en el horizonte — es esperable, no un bug: nadie en el sistema escanea partidos a 17 días
vista, ni tendría sentido (cuotas menos formadas, mayor riesgo de línea movida antes del partido). Suite
completa (281 tests) en verde tras el cambio.

**Nota para retomar esta tarea**: el resto de la "igualación de mercados" pedida (Sportium/Betfair con más
mercados que 1X2+una línea de Más/Menos, Bet777 sin córners/tarjetas) queda pendiente — se priorizó primero
comprobar por qué Winamax, la fuente que más se amplió el 2026-09-21, no estaba aportando nada en producción.

### Sportium ampliado a 5 mercados; Betfair bloqueado por Cloudflare al cambiar de mercado (2026-09-22)

**Sportium** (`providers/sportium.py`): la página de listado tiene un desplegable (`.ta-DropdownControl`) con 5
opciones, verificado en vivo navegando manualmente — hasta ahora solo se usaban "Ganador" (1X2) y "Goles
Totales" (Más/Menos). Se añadieron las otras tres: **Doble Oportunidad** (`DC`, orden 1X/12/X2), **Ambos
Marcan** (`BTTS`, orden Sí/No) y **Resultado al descanso** (`1X2_HT`). Córners/tarjetas/hándicap existen en la
ficha de cada partido (pestañas "Handicap (6)", "Todos (107)"...) pero no en este desplegable de listado, así
que exigirían navegar partido a partido (más lento, no implementado).

**Bug encontrado y corregido antes de dar el cambio por bueno**: "Goles Totales" se queda pegado como columna
secundaria aunque el desplegable seleccione otro mercado (confirmado en vivo: incluso en la carga inicial de la
página, antes de tocar nada, ya se ven dos bloques de mercado a la vez). La extracción original cogía **todos**
los botones de cuota del evento sin distinguir bloque, así que los 3 mercados nuevos venían con las 2 cuotas de
Goles Totales pegadas al final (`DC` con 5 valores en vez de 3) y `_parse_simple_market` los descartaba enteros
por no coincidir el recuento — 0 mercados nuevos en la primera prueba en vivo, pese a que la extracción parecía
correcta a simple vista en el navegador. Cada botón de cuota vive dentro de un `.ta-Market.ta-MarketType-<X>`
(`DBLC`=Doble Oportunidad, `BTSC`=Ambos Marcan, `H1RS`=Resultado al descanso, `HCTG`=Goles Totales, la columna
pegada); `_EXTRACT_MARKET_EVENTS_JS` ahora filtra por ese código antes de leer los botones. Verificado en vivo
tras el fix: 20 partidos × 4 mercados exhaustivos (100 % de cobertura en 1X2/DC/BTTS/1X2_HT) + Más/Menos con la
línea que decide cada partido — 100 mercados en total, frente a 40 antes del cambio.

**Betfair** (`providers/betfair.py`): el mismo mecanismo de "desplegable de mercado en la página de listado"
existe (`[class*="-marketSwitcher"]`, con `label[for="ppb:marketType:<ID>"]`) y tiene bastante más fondo que
Sportium — 19 opciones vistas en vivo, incluidas **Doble Oportunidad**, **Marcan ambos equipos** y ocho líneas
de **córners** (`TOTAL_CORNERS_6.5` a `15.5`, un mercado que hoy solo dan las casas de Altenar/Kambi). Se probó
en vivo: Doble Oportunidad y Ambos Marcan devuelven datos limpios con la misma extracción que ya usa 1X2/Más-Menos
(mismo orden 1X/X2/12 en Doble Oportunidad, distinto del que usan Sportium/Winamax/los comparadores — ojo si se
retoma). Los córners dan "No hay resultados" para toda la jornada en pre-partido, aunque sí aparecen listados en
el desplegable — probablemente solo se ofrecen en vivo.

**No se llegó a activar en producción.** Al repetir las pruebas para verificar el flujo completo, el simple
click en la opción de menú (el mismo mecanismo que ya usa el `OU_2.5` que llevaba meses funcionando) empezó a
redirigir a `betfair.es/cf-challenge` — la pantalla "Verificación de seguridad" de Cloudflare. Se comprobó
además que **el propio `OU_2.5` ya existente, sin tocar código, también lo dispara ahora** (probado con el
provider tal cual estaba commiteado, sin ninguno de los cambios de esta sesión): la fuente `betfair` llevaba ya
un tiempo aportando solo 1X2 en `docs/data.json` (9 mercados = 9 partidos, ningún `OU_2.5`), silenciado por el
`try/except` que rodea `_fetch_over_under` — no es una regresión de este cambio, es un bloqueo ya activo que
esta sesión solo puso en evidencia. Para comprobar si era un pico puntual por el volumen de pruebas de la propia
sesión (varias llamadas seguidas en pocos minutos), se esperaron 5 min y se repitió la prueba con el código
original sin tocar: **el bloqueo seguía activo**, así que no es solo un rate-limit momentáneo.

Siguiendo la política ya documentada del proyecto (sección 3 de `checklist.md`: no se implementa evasión de
protecciones anti-bot sin discutirlo antes), **no se ha intentado sortear el challenge**. Decisión tomada con
el usuario: los mercados nuevos de Betfair no se implementaron, y además se **desactivó** la llamada a
`_fetch_over_under` (el `OU_2.5` que ya existía) en `_fetch_markets_async` — el código y su test se conservan
por si Betfair levanta el bloqueo más adelante, pero ya no se ejecuta en cada ciclo. Motivo: mantenerlo
disparando el challenge cada 5 minutos, 24/7, podía agravar el bloqueo sin aportar ningún mercado a cambio.
Betfair queda por tanto en solo 1X2 hasta que se revise de nuevo.

### Baloncesto y tenis en Altenar y Kambi (2026-09-24)

Hasta ahora baloncesto (`baloncesto_acb/euroleague/nba/eurocup`) y tenis (`tenis_atp`) solo los cubría
`CuotasAhoraProvider` (1X2 vía comparador, sin fuente directa). `GetAllSports` de Altenar confirmó en vivo
que el mismo widget público que ya se usa para fútbol (sportId 66) también sirve baloncesto (sportId 67,
~1000 eventos pre-partido ese día) y tenis (sportId 68, ~120); Kambi expone lo mismo por `listView/basketball/...`
y `listView/tennis/...`. Mismo esquema, mismo mecanismo sin navegador — solo hacía falta mapear su tabla de
mercados, así que `providers/altenar.py` y `providers/kambi.py` ahora aceptan cualquiera de los tres deportes.

- **Tenis**: ganador del partido y del primer set (`ML`/`ML_SET1`), hándicap de juegos del partido y del
  primer set (`AH`/`AH_SET1`), hándicap de sets (`SETS_AH`), total de juegos del partido/primer
  set/por jugador (`OU`/`OU_SET1`/`OU_HOME`/`OU_AWAY`), par/impar de juegos (`OE`/`OE_SET1`) y total de sets
  jugados (`SETS_OU`). El jugador se identifica por `competitorId` (Altenar) o `participant` (Kambi), igual
  que el 1X2 de fútbol — sin depender del texto, que cada casa escribe distinto.
- **Baloncesto**: ganador incl. prórroga (`ML`), habrá prórroga (`OT`, sí/no), hándicap y total de puntos
  incl. prórroga (`AH`/`OU`, con variantes por equipo), par/impar, y los mismos cuatro mercados
  (hándicap/total/empate-no-apuesta/par-impar) por mitad (`_HT`/`_2H`) y **por cuarto** (`_Q1".."_Q4`).
  Quedan fuera a propósito "margen de victoria" y "cuarto/mitad con más puntos": no son un mercado exhaustivo
  de 2/3 resultados limpio (hay bloques de "otro" o pueden empatar entre periodos).
- **El cuarto es un caso especial en Altenar**: a diferencia de fútbol/tenis, donde cada periodo tiene su
  propio `typeId` (p.ej. `18`=total del partido, `68`=total 1ª mitad), baloncesto **reutiliza el mismo
  `typeId`** para los 4 cuartos (verificado en vivo: `236`="Totales" del cuarto que sea) y solo el texto de
  `market["name"]` dice cuál es ("Primer Cuarto", "1° cuarto"... Altenar usa **los dos formatos** según el
  mercado). `providers/altenar.py:_quarter_number` reconoce ambos; si el texto no encaja con ninguno el
  mercado se descarta entero en vez de adivinar el cuarto (mismo criterio de "fallo seguro" que el resto del
  proyecto). Kambi en cambio sí trae el cuarto como sufijo de la label (`"... - Quarter 1"`), así que ahí es
  un caso más del sufijo de periodo genérico que ya usaba `_HT`/`_2H`.
- **El filtro de femenino ahora es específico de fútbol**: `providers/filters.py:is_excluded` recibe el
  deporte y solo aplica `EXCLUDE_WOMENS_FOOTBALL` cuando es `"futbol"`. En baloncesto/tenis la WNBA/WTA son
  producto mayoritario y con nombres consistentes entre casas (a diferencia del fútbol femenino, que rara vez
  cruza por eso mismo) — aplicar el mismo filtro ahí solo habría restado cobertura sin motivo real.
- Verificado en vivo con datos reales (no solo unitario): Altenar+Kambi juntos cruzan tenis y baloncesto
  ENTRE plataformas igual que ya hacían en fútbol (ejemplo real capturado: `Hapoel Tel-Aviv vs. Bayern`,
  mercado `OU_169.5`, Betway 1.74 Over / Paf 2.10 Under).

### Casas white-label sin fuente pública viable (recomprobado en vivo 2026-09-24)

Siguiendo la pista de "buscar la plataforma B2B detrás de una casa bloqueada" (la que desbloqueó 7+ casas vía
Altenar/Kambi), se recomprobaron con Playwright headless real (no solo el navegador interactivo) las tres
pendientes de `estudio_tecnicas_otros_bots.md`:

- **Suertia/OlyBet**: la web de marketing (`suertia.es`) redirige a `olybet.es`; el sportsbook real vive en
  `apuestas.olybet.es` (Nuxt.js), confirmado por red que corre sobre **GiG Sport / Sportnco**
  (`fonts/icons/gig/GiGSport.ttf`, estado `__NUXT__` con `sportx-static.sportnco.com`). A diferencia de
  Altenar/Kambi, aquí **no hay una API JSON pública aparte**: las cuotas vienen ya renderizadas en el HTML
  (server-side, todo dentro de `__NUXT__`), así que en teoría bastaría un `httpx.get()` sin navegador. En la
  práctica un WAF (**F5/Volterra**, `server: volt-adc`) devuelve "Request Rejected" tanto a `httpx` como a un
  `chromium.launch(headless=True)` real — con la MISMA IP residencial (Orange España) con la que el navegador
  interactivo de esta sesión sí cargó la página completa con cuotas reales. Mismo patrón que Interwetten: el
  navegador interactivo no es un fiable "esto no está bloqueado", hace falta el lanzamiento headless real.
  No implementado — bloqueo de fingerprint, no de IP ni de anti-bot JS visible.
- **Betsson**: la web de apuestas (`betsson.es/apuestas-deportivas`) SÍ carga completa con Playwright headless
  (200, shell del widget de sportsbook presente) — mejor que el diagnóstico anterior. Pero el hándicap real
  sigue el mismo que documentaba `checklist.md`: `POST /api/fraud/v1/groupib/tokens/generate` devuelve
  **403 de forma consistente** (repetido varias veces durante la carga), el paso de verificación antifraude
  (Group-IB) que el widget necesita antes de poder pedir cuotas. Reconfirmado tal cual, no es un diagnóstico
  obsoleto.
- **Luckia**: sigue devolviendo el challenge de Cloudflare ("Just a moment...", 403) con Playwright headless
  real. Sin cambios respecto a `checklist.md`.

Ninguna de las tres se implementa (mismo criterio de siempre: sin evasión de anti-bot). Quedan cubiertas solo
indirectamente vía CuotasAhora/BetExplorer, como hasta ahora.

El arbitraje deportivo no es ilegal en España (Ley 13/2011), pero cada casa de apuestas puede limitar o cerrar
cuentas por sus propios términos y condiciones. El scraping debe hacerse de forma moderada y revisando los
términos de servicio de cada operador. Ver el documento base para más detalle.
