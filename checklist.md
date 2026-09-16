# Checklist

Contexto (actualizado 2026-09-16): este documento se creó originalmente pensando solo en Bigwin/Bet365,
antes de probar nada en vivo. Desde entonces se ha probado con Playwright real, en vivo, una veintena de
casas DGOJ. Este documento ahora recoge el resultado real de todas ellas, unificado en un solo sitio (antes
parte de esta info vivía también en el README). Corrección importante sobre el contexto original: Kirolbet
**no** quedó resuelto como decía la primera versión de este checklist — está bloqueado por Akamai (ver
sección 0).

**Actualización 2026-09-16 (tarde): CuotasAhora.com desbloquea varias de estas indirectamente.** Ver el
bloque dedicado justo debajo de la tabla de bloqueadas — cambia el diagnóstico de bet365, Bwin, Codere,
Luckia y William Hill de "sin vía" a "cubiertas, aunque no en directo".

## 0. Resultado verificado en vivo (no teórico) — 2026-09-16

**Funcionan (4 fuentes, integradas en `main.py` y `scripts/scan_once_action.py`):**

| Casa / fuente | Provider | Notas |
|---|---|---|
| Sportium | `providers/sportium.py` ✅ | Playwright headless normal, sin trucos. 1X2 y over/under (Goles Totales, línea variable por partido) verificados. |
| Betfair | `providers/betfair.py` ✅ | Playwright headless normal. 1X2 y over/under 2,5 goles verificados sobre el listado completo de LaLiga. |
| Winamax | `providers/winamax.py` ✅ | Playwright headless normal. Cuotas en coma decimal española, convertidas a float. Solo 1X2 (over/under solo en la ficha de cada partido, no en el listado — no implementado). |
| **CuotasAhora.com** (comparador, no una casa) | `providers/cuotasahora.py` ✅ | Playwright headless. Agrega 1X2 de hasta 14 casas por partido en una sola `<table>` HTML. Ver bloque dedicado abajo. |

**Bloqueadas para scraping directo (con causa técnica confirmada):**

| Casa | Causa | Detalle |
|---|---|---|
| Kirolbet | Akamai Bot Manager | API JSON (`/Api/esp/Lib/Competicion`) ya localizada y parseada en `providers/kirolbet.py`, pero Akamai devuelve 403 incluso con `fetch()` real ejecutado dentro de la página — detecta el propio Chromium automatizado (fingerprint), no solo el patrón de la petición. |
| Bwin | reCAPTCHA Enterprise invisible | Se dispara nada más entrar y bloquea la petición que trae los datos del widget de cuotas. **Ahora cubierta indirectamente vía CuotasAhora.com** (ver abajo). |
| Betsson | API antifraude propia | 403 en `/api/fraud/v1/groupib/tokens/generate`, antes de poder pedir cuotas. |
| Codere | Bloqueo de red | Denegación directa, sin completar el intercambio HTTP normal desde el entorno de pruebas (cloud). **Ahora cubierta indirectamente vía CuotasAhora.com** (ver abajo). |
| Suertia (OlyBet) | Bloqueo de red | "Access Denied" servido por el proveedor de infraestructura, mismo patrón que Codere. |
| bet365 | Anti-bot agresivo | Spinner de carga infinito con cualquier navegador automatizado; nunca renderiza cuotas. Es la protección más dura de todas las probadas. **Ahora cubierta indirectamente vía CuotasAhora.com** (ver abajo). |
| Marca Apuestas | Cloudflare / API propia | Challenge "Just a moment..." o 403 directo en `sportswidget.../refresh-bets`. |
| Luckia | Cloudflare | Challenge JS "Just a moment...". **Ahora cubierta indirectamente vía CuotasAhora.com** (ver abajo). |
| Interwetten | Cloudflare | Challenge JS "Just a moment...". |
| William Hill | Bloqueo de IP explícito | La web devuelve literalmente el mensaje "Data Centre block" — es el único bloqueo que se declara a sí mismo como por rango de IP, no por fingerprint. **Ahora cubierta indirectamente vía CuotasAhora.com** (ver abajo). |

### CuotasAhora.com: comparador de cuotas como vía indirecta (hallazgo 2026-09-16)

En vez de pelear con el anti-bot de cada casa bloqueada una por una, se probó scrapear un **comparador**
(cuotasahora.com, la versión española de OddsPortal, mismo grupo). Resultado, verificado en vivo con
Playwright real (no teórico):

- **Sin bloqueo anti-bot.** Solo dos gates estándar de UI que hay que aceptar una vez por sesión de
  navegador: verificación de edad 18+ y el banner de cookies OneTrust — ninguno es un WAF, son botones
  normales (`page.click(...)`).
- **Cada partido tiene su propia página** (`/football/h2h/equipo-a/equipo-b/`) con una tabla HTML normal
  (no CSS modules con hash, un `<table>` de verdad) listando 1X2 de hasta **14 casas a la vez**: 1xBet.es,
  888sport, bet365, Betway, bwin.es, Codere, Luckia.es, Paf.es, Retabet, Speedybet.es, Sportium.es,
  Versus.es, William Hill, Winamax.es.
- **Su API interna sí está deliberadamente cifrada** (`/proxy/ajax-nextgames-odds/...` devuelve un blob
  base64 de contenido encriptado, técnica anti-scraping conocida de OddsPortal) — pero como el propio
  navegador la descifra para pintar la tabla, no hace falta romper el cifrado: se lee el DOM ya renderizado,
  exactamente igual que con Sportium/Betfair/Winamax. No es evasión de nada, es scraping normal de HTML.
- **Coste**: ~75-80s para escanear toda la jornada de LaLiga (una `page.goto` por partido, ~16-18 partidos).
  Sale a cuenta: un solo provider desbloquea de golpe bet365, bwin, Codere, Luckia y William Hill
  (bloqueadas en directo) más 888sport, Betway, Retabet, Paf.es, Speedybet.es, Versus.es (no probadas antes).
- **Filtro en `providers/cuotasahora.py` (`ALLOWED_BOOKMAKERS`)**: excluye a propósito **Sportium.es/
  Winamax.es** aunque aparezcan en la tabla, porque ya se scrapean en directo — mezclar ambas fuentes para la
  misma casa arriesgaría comparar una cuota fresca con una del comparador potencialmente desfasada unos
  segundos/minutos. **1xBet.es sí se incluye** (ver verificación DGOJ abajo — la sospecha inicial de que no
  tuviera licencia era incorrecta).
- ✅ **Licencias DGOJ verificadas a mano (2026-09-16)**: la URL directa a `ordenacionjuego.es` daba 404, la
  correcta es el buscador de operadores
  (`ordenacionjuego.es/operadores-juego/operadores-licencia/operadores`). Se repasaron las 78 fichas de
  operadores con licencia, página a página (búsqueda por nombre no siempre encontraba por marca comercial —
  p.ej. buscar "bet365" o "bwin" no daba resultados porque el campo solo indexa la razón social, "HILLSIDE
  ESPAÑA LEISURE" y "ELECTRAWORKS CEUTA" respectivamente — paginar entero fue más fiable). Resultado:
  **todas** las casas usadas por este sistema tienen licencia vigente, incluido 1xBet.es (WAGERFAIR, S.A.).
  De propina, se confirmó que Paston (EUROAPUESTAS ONLINE), Botemanía (GAMESYS SPAIN), Zebet (ZEBETTING Y
  GAMING) y PokerStars Sports (TSG INTERACTIVE) también tienen licencia — de la lista de "sin confirmar" de
  abajo, aunque su scraping directo sigue sin implementarse. El panel web (`docs/app.js`,
  `DGOJ_LICENSED_BOOKMAKERS`) marca en rojo cualquier casa fuera de esta lista verificada. Es una foto de un
  momento dado — la DGOJ actualiza el registro mensualmente, revisar de nuevo si pasa mucho tiempo.
- Verificado en pipeline completo (las 4 fuentes juntas + cruce de eventos): márgenes realistas, incluidas
  dos surebets pequeñas y plausibles (+0.27% Betis-Getafe entre Codere/Winamax/Paf, +2.09% Valencia-Real
  Sociedad entre Paf/Sportium/Codere) — nada de los falsos positivos del 30-40% de los bugs anteriores.

**Sin confirmar / de menor prioridad ahora** (candidatas si se quiere ampliar aún más, pero ya no son
urgentes dado que CuotasAhora cubre mucho de golpe):

Paston, PokerStars Sports, Zebet, Botemanía — cargaron sin 403/Cloudflare/CAPTCHA visible en su momento,
pero no se llegó a localizar con certeza el contenedor DOM real de la tabla de cuotas. (888sport ya quedó
cubierto vía CuotasAhora, se quita de esta lista). Las 4 tienen licencia DGOJ confirmada (ver verificación
arriba), así que si algún día se scrapean en directo no haría falta añadir nada al filtro de licencias.

**Bugs de cruce de eventos encontrados y corregidos con datos reales** (no relacionados con bloqueos, pero
relevantes para la fiabilidad del sistema): comparar el string completo del evento confundía partidos
distintos que comparten texto ("Atlético Madrid vs. Osasuna" con "Atlético Madrid vs. Real Madrid"), y la
similitud de texto genérica confundía equipos con nombres cortos parecidos por casualidad ("Barcelona"
vs. "Celta"). Solucionado con una tabla de alias curada a mano (`engine/team_aliases.py`) en vez de depender
solo de similitud de texto. Sin esto, el sistema mostraba "surebets" falsas del 30-40%.

## 1. Diagnóstico antes de tocar código

- [x] Confirmar el tipo de bloqueo exacto por casa — hecho para las 10 casas bloqueadas listadas en la
      sección 0 (Akamai, Cloudflare, reCAPTCHA Enterprise, antifraude propio, bloqueo de red/IP, o spinner
      infinito sin causa expuesta en el caso de bet365).
- [x] Comprobar si el bloqueo es por IP/datacenter o por fingerprint del navegador — diferenciado caso a
      caso en la sección 0 (William Hill se declara explícitamente por IP; Akamai/Cloudflare/reCAPTCHA son
      fingerprint/comportamiento; Codere/Suertia parecen red pero no confirmado al 100% que no sea también
      fingerprint).
- [x] Mirar si el bloqueo aparece también en la home o solo al llamar a la API/endpoint de cuotas — varía:
      Kirolbet carga la home pero bloquea la API; Bwin/Cloudflare bloquean antes de cargar nada; Betsson
      bloquea en su endpoint de token de sesión.
- [ ] Revisar si existe app móvil de las casas bloqueadas con endpoints menos protegidos que la web — **no
      probado todavía** para ninguna casa. Sigue siendo una vía pendiente genuina.

## 2. Técnicas a probar para extraer los datos de las casas bloqueadas

- [x] ~~Repetir el patrón "cargar home para generar cookies, reutilizar sesión para llamar al JSON interno"~~
      — probado en Kirolbet exactamente así (Playwright headless + `context.request.get()` y luego `fetch()`
      real dentro de la página reutilizando la sesión): **no funcionó**, Akamai bloquea igual. Descartado
      como solución por sí sola para bloqueos de fingerprinting (Akamai/Cloudflare/reCAPTCHA); sigue siendo
      válido para casas sin ese tipo de protección.
- [x] Interceptar tráfico de red para localizar el endpoint real de cuotas — hecho para Kirolbet (API JSON
      ya localizada y parseada en `providers/kirolbet.py`); pendiente de intentar en las 5 casas sin
      confirmar de la sección 0.
- [ ] Contexto persistente / `storage_state` para no repetir el challenge en cada ejecución — **no probado**.
      Posible siguiente paso para Kirolbet/Cloudflare antes de descartarlas del todo, aunque no resuelve el
      fingerprinting inicial, solo evita repetirlo.
- [ ] `playwright-stealth` / `patchright` — **no implementado, decisión pendiente**. Es evasión activa de un
      control de seguridad desplegado a propósito por el operador (no solo scraping normal); no se ha
      construido sin discutirlo explícitamente contigo primero. Candidatas si se decide seguir esta vía:
      Cloudflare (Marca Apuestas/Luckia/Interwetten) tiene algo más de historial de éxito con stealth que
      Akamai (Kirolbet) o reCAPTCHA Enterprise (Bwin); bet365 es la que menos probabilidad tiene de funcionar
      aun con stealth.
- [ ] Igualar cabeceras/fingerprint completo a un navegador real (locale, timezone, fuentes, viewport
      coherentes) — no aplicado de forma sistemática; parte de la misma decisión de stealth de arriba.
- [ ] Espaciar peticiones con jitter — no relevante todavía: los bloqueos actuales ocurren en la
      primera petición, no por volumen/patrón de tráfico.
- [ ] Proxy residencial/móvil por IP de datacenter — **candidato prioritario, no probado**. A diferencia de
      stealth, no es evasión de fingerprinting, solo evita el bloqueo por rango de IP. Empezar por William
      Hill (bloqueo de IP explícito y confirmado) antes que por Codere/Suertia (bloqueo de red pero causa no
      100% confirmada) o por las de fingerprinting (donde probablemente no basta con cambiar de IP).
- [ ] Loguearse con cuenta real para relajar el WAF — no probado, sigue siendo una opción válida a explorar
      si se decide invertir más en alguna casa concreta.
- [ ] Revisar si el proveedor de cuotas es un tercero (Kambi, Betradar/Sportradar, OpenBet) tras un
      iframe/widget — no investigado para ninguna de las bloqueadas.
- [ ] Buscar proyectos open source de scraping de bet365 en GitHub como referencia — no hecho; dado que
      bet365 fue la protección más dura encontrada, de baja prioridad frente a las 5 casas sin confirmar de
      la sección 0.

## 3. Límite y riesgo (releer antes de insistir demasiado)

- [ ] Revisar los términos de servicio concretos de cada casa bloqueada antes de invertir en saltarse su
      protección — pendiente, aplica sobre todo si se decide entrar en la vía de stealth de la sección 2.
- [x] Se decidió explícitamente **no** implementar stealth/evasión activa sin discutirlo contigo primero,
      precisamente por este riesgo (cierre de cuenta real de apuestas, no solo del scraper).
- [ ] Definir un límite de tiempo/esfuerzo de ingeniería para las casas más difíciles (bet365, Bwin) frente a
      seguir sumando casas sin confirmar (sección 0) — pendiente de decidir contigo.

## 4. Otras fuentes para comparar cuotas y detectar surebets sin depender de las bloqueadas

- [x] Sumar más casas con licencia DGOJ con menos protección anti-bot — **hecho**: Sportium, Betfair y
      Winamax ya dan cobertura horizontal real (3 casas, suficiente para que el motor de arbitraje compare
      cuotas de verdad). Siguiente ampliación natural: las 5 sin confirmar de la sección 0.
- [ ] Usar Betfair Exchange (API oficial, no el scraping actual del sitio de apuestas fijas) como cuota
      "líquida" de referencia — no probado; hoy `providers/betfair.py` scrapea la web de apuestas normales,
      no la Exchange API.
- [x] Evaluar APIs de cuotas de terceros — The Odds API investigada y **descartada** (ver más abajo, sección
      0): no cubre casas españolas relevantes y el tier gratis no alcanza. OddsJam/Pinnacle API sin evaluar
      todavía, de menor prioridad ahora que CuotasAhora.com ya da cobertura amplia gratis.
- [x] Comparadores públicos (oddsportal.com / cuotasahora.com) — **hecho, mucho más que un simple
      contraste manual**: `providers/cuotasahora.py` scrapea el comparador en vivo y desbloquea
      indirectamente bet365, bwin, Codere, Luckia y William Hill (ver sección 0). El otro comparador
      probado, The Odds API, se descartó: no cubre las casas españolas relevantes (sin Sportium, sin
      Winamax España, Betfair sin confirmar si es la .es) y su tier gratis (500 créditos/mes) no da para
      escanear cada 5 min.
- [ ] Programas de afiliados con datafeed oficial (XML/JSON) de alguna de las casas bloqueadas — no
      investigado para ninguna.
- [ ] Herramientas SaaS de arbitraje (RebelBetting, BetBurger) como alternativa de pago al scraping propio —
      no evaluado.
- [x] Documentar qué casas quedan cubiertas por scraping propio y cuáles no — hecho en README.md
      ("Estado real de los scrapers") y en este checklist (sección 0).

## 5. Fiabilidad del `schedule` de GitHub Actions (hallazgo y decisión, 2026-09-16)

**Problema detectado**: el panel web (GitHub Pages) llevaba ~3h sin actualizarse pese a que
`.github/workflows/scan.yml` tiene `schedule: cron: "*/5 * * * *"`. Confirmado con la API real de GitHub
Actions del repo (no es un bug del código): hubo huecos de **~5 horas entre ejecuciones programadas** en vez
de 5 minutos (última ejecución programada exitosa a las 06:42 UTC, la anterior a las 01:34 UTC — un gap de 5h
entre ambas). El workflow está `state: active` y no se tocó nada en `scan.yml` entre medias. Causa: GitHub
**no garantiza** el intervalo del trigger `schedule` — en picos de carga de su infraestructura retrasa o
descarta directamente ejecuciones programadas, y esto es especialmente notorio con intervalos cortos como
cada 5 min (limitación documentada de GitHub, no algo específico de este repo).

**Solución implementada — disparo externo vía `workflow_dispatch`**: en vez de depender solo del `schedule`
interno (que sí se deja puesto como red de respaldo, no estorba gracias al `concurrency` del workflow), un
cron externo gratuito (cron-job.org) llama cada 5 min a la API de GitHub
(`POST /repos/hugogpmr/surebets/actions/workflows/scan.yml/dispatches`) para disparar el workflow al
instante, sin pasar por la cola de "scheduled events" de GitHub que es la que falla. Requiere un
fine-grained personal access token (scope: solo Actions read/write de este repo) que el usuario crea y pega
él mismo en cron-job.org — paso a paso completo en
[deploy/README_DEPLOY.md](deploy/README_DEPLOY.md#el-schedule-de-github-actions-no-es-fiable-a-5-minutos-comprobado-2026-09-16).

**Redundancia adicional (VM 24/7, Opción B) — evaluada y descartada por ahora**:

- Se consideró montar una segunda vía completamente independiente de GitHub Actions (una VM con `main.py`
  corriendo 24/7 vía systemd, ver Opción B de `deploy/README_DEPLOY.md`) como "doble seguridad" por si
  GitHub como infraestructura fallara entero (no solo el trigger `schedule`).
- **Oracle Cloud Always Free** (gratis para siempre, specs generosas — hasta 24GB RAM en shape ARM, de sobra
  para Chromium/Playwright) era la opción natural: la cuenta ya existía, pero quedó **inaccesible** — login
  dice que el usuario no existe y la recuperación de usuario por email no llega nada. Probable causa:
  cuenta reclamada/suspendida por Oracle por inactividad (patrón conocido en su tier gratuito). Pendiente:
  si se quiere insistir, habría que entrar con el "Cloud Account Name" (nombre de tenancy) en vez de
  recuperar usuario, o abrir un ticket de soporte con Oracle (puede tardar días) — no intentado a fondo.
- **Alternativas de pago comparadas**: Hetzner CX22 (2 vCPU/4GB, ~3.79€/mes) es la más barata con specs
  suficientes. AWS descartado: tras los 12 meses gratis, un `t3.micro` (specs peores, 1GB RAM) sale a
  ~9-10 USD/mes, más caro y más justo de RAM que Hetzner. Google Cloud `e2-micro` es gratis para siempre
  pero con solo 1GB RAM compartida — va muy justo para Chromium, descartado por poco fiable. Contabo/
  DigitalOcean/Vultr/Linode: precio similar a Hetzner, sin ventaja clara.
- **Decisión**: no se paga una VM solo por esta redundancia extra. El fallo real era el trigger `schedule`
  (ya arreglado, gratis, con cron-job.org); que GitHub como infraestructura entera esté caída es un riesgo
  bastante más raro, y pagar 3.79€/mes recurrentes solo para cubrir ese residual no compensa ahora mismo.
  **Revisar esta decisión si**: (a) en algún momento se quiere recuperar los comandos interactivos de
  Telegram (`/hoy`, `/ahora`, `/stats`, que no funcionan solo con GitHub Actions porque no hay proceso
  escuchando 24/7) — ahí sí justificaría pagar Hetzner, pero sería por esa función, no por redundancia; o
  (b) se recupera el acceso a la cuenta de Oracle más adelante, lo que haría la VM gratis y quitaría el
  dilema de precio.

## 6. Ampliación de mercados y competiciones (iniciado 2026-09-16)

**Contexto**: hasta ahora el sistema solo cubría 1X2 (+ OU_2.5 en Sportium/Betfair) de LaLiga. Se evaluó qué
ampliar primero por relación esfuerzo/cobertura, dado que cada casa scrapeada en directo (Sportium, Betfair,
Winamax) tiene su propio DOM y hay que verificar cada mercado/competición nueva en vivo antes de darlo por
bueno (mismo criterio que el resto de este documento).

**Hecho:**
- [x] `providers/cuotasahora.py`: mercados "Ambos equipos marcan" (`BTTS`) y "Doble oportunidad" (`DC`),
      verificados en vivo contra partidos reales de Champions League. Se generalizó `_EXTRACT_ODDS_TABLE_JS`
      para leer los nombres de resultado desde la cabecera `<thead>` de la tabla en vez de fijarlos a mano,
      porque la tabla es idéntica en forma (casa | resultado... | payout%) en las tres pestañas probadas
      (1X2, BTTS, Doble oportunidad) - así, sumar otra pestaña de mercado con esa misma forma de tabla plana
      es una entrada más en `EXTRA_MARKET_TABS`, no una función nueva. Ver detalle y motivación completa en
      README.md ("Mercados soportados").
- [x] Competición Champions League, solo en CuotasAhora (`league_urls["futbol_champions"]`) - de momento no
      sumada a Sportium/Betfair/Winamax porque `engine/team_aliases.py` solo cubre los 20 equipos de LaLiga
      y el fallback de similitud genérica es justo lo que causó los falsos positivos del 30-40% documentados
      en la sección 0 del README; sumarla a más de un proveedor sin ampliar esa tabla antes arriesga
      repetir ese bug con equipos europeos. CuotasAhora no tiene ese riesgo porque agrega varias casas en su
      propia tabla por partido (no necesita cruzar el evento con otro proveedor para arbitrar).
- [x] Verificado en vivo el pipeline completo tras el cambio: 18 partidos de Champions League, extracción
      correcta de 1X2/BTTS/DC con cuotas reales de bet365/888sport/Betway/etc. Un puñado de partidos (3-5 de
      18 en pruebas repetidas) falla por timeout cargando la tabla en `_fetch_match` - no es una regresión
      de este cambio, ya existía ese patrón de fallo transitorio por partido (try/except + log + skip, igual
      que antes); no investigado a fondo si es rate-limiting del sitio por visitar muchas páginas seguidas.

**Pendiente / candidatas siguientes (por esfuerzo, de menor a mayor):**
- [ ] Mercados adicionales de CuotasAhora con la misma tabla plana, vistos en el desplegable "Más" del
      partido pero no confirmados en detalle: "Resultado sin empate" (draw no bet), "Par/Impar",
      "Hándicap europeo" (línea fija con selector, a confirmar si es tabla plana o acordeón como
      "Más/Menos"), "Marcador correcto" (probablemente demasiadas filas/outcomes para ser útil en
      arbitraje). Añadir una entrada a `EXTRA_MARKET_TABS` por cada uno tras verificar en vivo su forma de
      tabla.
- [ ] "Más/Menos de" (over/under) de CuotasAhora: a diferencia de 1X2/BTTS/DC, agrupa las cuotas en un
      acordeón por línea de goles (0.5, 1.5, 2, 2.25, 2.5...) que hay que expandir fila a fila para ver las
      casas - no es la misma tabla plana, necesitaría una extracción dedicada. Cubriría de golpe más líneas
      de las que hoy solo dan Sportium (línea variable) y Betfair (fija en 2,5).
- [ ] Ampliar `engine/team_aliases.py` con los equipos de Champions League (y de cualquier otra competición
      europea que se quiera sumar) como paso previo a activar esa competición también en Sportium, Betfair y
      Winamax - hoy esos tres siguen solo en LaLiga.
- [ ] Otras competiciones de fútbol candidatas una vez ampliados los alias: Segunda División (misma casa de
      alias que LaLiga necesitaría su propia tabla, equipos distintos), Premier League, Europa League.
- [ ] Otros deportes (baloncesto, tenis): no evaluado todavía qué estructura de DOM usa cada sitio para esos
      deportes - probablemente distinta a la de fútbol en cada casa, así que cada uno necesitaría su propia
      verificación en vivo antes de asumir que el patrón actual (URL de competición + selectors ya conocidos)
      se puede reutilizar sin más.

## 7. Migración a scraper local: viabilidad evaluada (2026-09-16)

**Contexto**: el usuario planteó un nuevo documento
([Arquitectura actual y transición...](<Arquitectura actual y transición de tu proyecto de surebets con GitHub Actions, web en GitHub y bot de Telegram.md>))
proponiendo mover la ejecución del scraper fuera de GitHub Actions por los bloqueos de IP, empezando por
correrlo en local (coste cero) antes de valorar una VPS con IP española. Se evaluó la viabilidad concreta
para este repo, no en abstracto.

**Hallazgo clave — el problema de IP ya está confirmado con datos reales, no es solo teoría del documento:**

- El propio repo ya tenía un diagnóstico en curso: el commit `4374168` ("debug: imprimir IP/pais del runner
  en scan.yml") documenta que **Betfair y CuotasAhora devuelven 0 datos cuando corren en GitHub Actions**,
  pero funcionan bien en local — hipótesis explícita del propio historial: geo-bloqueo, porque ambas casas
  tienen licencia DGOJ (obligadas a restringir a España) y los runners de GitHub-hosted corren fuera.
- Se ha verificado esa hipótesis contra el snapshot real que consume el panel web (`docs/data.json`,
  generado exclusivamente por runs de GitHub Actions): **todas** las comparaciones presentes usan solo
  `sportium` y/o `winamax` como bookmakers. Ni una sola aparición de `betfair` ni de ningún bookmaker que
  solo llega vía CuotasAhora (bet365, bwin, codere, luckia, william hill, 888sport, betway, retabet, paf,
  speedybet, versus, 1xbet). Es decir: **2 de las 4 fuentes activas (Betfair y CuotasAhora) están
  efectivamente muertas en producción ahora mismo**, no por un bug de código sino por la IP del runner —
  justo el problema que motiva el documento del usuario. Esto no es un supuesto, es el estado real
  documentado en el propio JSON que sirve GitHub Pages hoy.

**Viabilidad de "scraper local primero": alta, y de esfuerzo de implementación bajo.** Motivo: no hace
falta escribir código nuevo, todo el que hace falta ya existe y está probado:

- `scripts/scan_once_action.py` ya hace exactamente un ciclo de escaneo + export a
  `docs/data.json` + persistencia de dedupe en `data/active_opportunities.json` — es agnóstico de dónde
  corre (no depende de nada específico de GitHub Actions salvo que hoy lo invoca `scan.yml`).
- El `.venv` ya existe en el propio PC del usuario (`.venv/Scripts/python.exe`), con Playwright y Chromium
  ya instalados y probados en local — es el mismo entorno donde ya se confirmó que Betfair/CuotasAhora sí
  funcionan.
- Lo único que faltaría por escribir es un script wrapper (`.ps1` o `.bat`) que replique en local los 3
  pasos que hoy hace `scan.yml` fuera del propio scraping: `python scripts/scan_once_action.py` →
  `git add data/ docs/data.json` → `git commit` + `git push` (si hay cambios) — calcado del bloque
  "Guardar estado y base de datos actualizados" del workflow, sin lógica nueva.
- Ese wrapper se registraría en el **Programador de tareas de Windows** (Task Scheduler) con un disparador
  de intervalo (cada 5-15 min, igual que ahora), en vez de en `schedule`/cron-job.org.

**Lo que cambia respecto a hoy y trade-offs a decidir con el usuario (no implementado todavía, pendiente de
confirmación explícita porque toca automatización en producción):**

- [ ] **Evitar doble ejecución**: si se activa el runner local hay que apagar el disparo actual (el cron de
      cron-job.org que llama a `workflow_dispatch`, y opcionalmente también el `schedule` interno de
      `scan.yml`) — si ambos corren a la vez se arriesgan carreras de `git push` (non-fast-forward) sobre
      `data/` y `docs/data.json`. Alternativa más simple: dejar `scan.yml` solo con `workflow_dispatch`
      manual (sin cron ni schedule) como respaldo puntual, no como fuente activa.
- [ ] **Disponibilidad**: a diferencia de GitHub Actions (corre pase lo que pase), el runner local solo
      escanea/actualiza mientras el PC del usuario esté encendido y con red. El panel web se queda
      desactualizado y no llegan avisos nuevos mientras el PC esté apagado/dormido — trade-off aceptado
      explícitamente por el usuario a cambio de coste cero, pero conviene que Task Scheduler tenga marcada
      la opción "Wake the computer to run this task" si el PC entra en suspensión, o si no, asumir que solo
      escanea en horario en que el PC está encendido.
- [ ] **Bot con comandos interactivos** (`/hoy`, `/ahora`, `/stats`): el wrapper de arriba mantiene el mismo
      modo "solo avisos" que ya tiene `scan_once_action.py` hoy en Actions (no hay proceso escuchando
      permanentemente Telegram). Si se quisiera recuperar esos comandos sin pasar todavía a VPS, haría falta
      dejar `main.py` corriendo continuamente en el PC en vez del wrapper por intervalos — viable, pero
      `main.py` hoy **no** exporta a `docs/data.json` (solo lo hace `scan_once_action.py`); habría que
      añadirle esa llamada a `storage.db.export_snapshot` + el `git push` periódico si se quiere ese modo.
      No urgente: el usuario no ha pedido explícitamente recuperar los comandos ahora mismo.
- [ ] **Credenciales**: el token de Telegram pasaría de vivir en un GitHub Secret a vivir en el `.env` local
      (ya es el modelo que usa `main.py` en local hoy) — sin cambios de riesgo siempre que `.env` siga fuera
      de git (ya está en `.gitignore`).
- [ ] **Decisión pendiente de confirmar con el usuario antes de tocar nada en producción**: si procedo a (a)
      crear el script wrapper + instrucciones de Task Scheduler, y (b) desactivar el cron de cron-job.org y
      dejar `scan.yml` solo en `workflow_dispatch` manual. Ambas cosas tocan automatización ya desplegada y
      en marcha, así que se pide confirmación explícita en vez de aplicarlas directamente.

**Conclusión**: la idea del usuario no es solo viable, sino que los datos de producción ya muestran que el
problema que la motiva es real y activo (Betfair/CuotasAhora a 0 en Actions). Es además la opción de menor
esfuerzo de las evaluadas en la sección 5/6: reutiliza el 100% del código ya escrito y probado, sin VPS ni
cuenta cloud nueva, y dado que ya se decidió no pagar una VM solo por redundancia (sección 5), tiene sentido
probar primero si el scraper local basta antes de valorar el salto a una VPS con IP española (sección 6.1 del
documento de arquitectura) — que seguiría siendo la vía natural más adelante si el PC local no da la
disponibilidad suficiente.

**Estado: implementado y en producción (2026-09-16).** `scripts/local_scan.ps1` registrado como tarea
"SurebetsLocalScan" en el Programador de tareas de Windows de este PC (cada 5 min, con "despertar el equipo").
Dos bugs reales encontrados y corregidos durante la puesta en marcha (ver commit `51d3950`):

- El cache global de navegadores de Playwright (`%LOCALAPPDATA%\ms-playwright`) resultaba invisible para el
  proceso lanzado por el Programador de tareas, aunque el mismo fichero existía y se veía bien desde una
  sesión interactiva normal — causa exacta no diagnosticada (aislamiento de sesión/perfil propio del
  Programador de tareas en esta máquina). Solución: `PLAYWRIGHT_BROWSERS_PATH=0`, que instala/busca el
  navegador dentro del propio `.venv` del proyecto en vez de en el perfil de usuario.
- El script usaba por defecto el `DB_PATH` del `.env` local (pensado para pruebas manuales con `main.py`,
  `surebets.db` suelto en la raíz), no `data/surebets.db` — forzado explícitamente para que coincida con la
  base de datos real que lee el panel web y que está en git.

También se añadió `.gitattributes` con `merge=ours` para los ficheros de estado regenerados en cada ciclo
(`docs/data.json`, `data/active_opportunities.json`, `data/surebets.db`), necesario porque durante la
transición hubo dos escritores activos a la vez (el runner local nuevo y GitHub Actions/cron-job.org
todavía sin pausar) y un `git pull` normal abortaba el merge entero en cuanto ambos habían tocado el mismo
fichero regenerado. Requiere `git config merge.ours.driver true` en cada máquina que escriba a este repo
(ya configurado en este PC).

El usuario pausó el cron externo de cron-job.org el mismo día, quedando el runner local como único escritor
activo (GitHub Actions solo como respaldo manual vía `workflow_dispatch`). Efecto colateral de las pruebas en
vivo: se detectaron y notificaron por Telegram varias surebets reales, incluidas un par de márgenes
sospechosamente altos (candidatos a falso positivo, no relacionado con esta migración) — investigación
delegada a una tarea aparte en vez de bloquear este despliegue. Ver sección 8 para el resultado.

## 8. Márgenes anómalos (>20%) en CuotasAhora: causa encontrada y corregida (2026-09-16)

**Síntoma**: durante las pruebas en vivo de la sección 7 se detectaron y notificaron por Telegram varias
"surebets" con márgenes disparatados para un mercado de solo 2 resultados — Galatasaray vs. Barcelona (BTTS)
70.41%, Valencia vs. Real Sociedad (BTTS) 36.04%, además de otras vistas en corridas de prueba anteriores
(RB Leipzig-PSV 26.46%, Bodo/Glimt-Dortmund 45.59%). Los márgenes reales de este sistema son de un orden de
magnitud menor (0.27%-5%, ver sección 0).

**Causa confirmada contra la web en vivo** (no hipótesis): se volvió a abrir a mano la página del partido
Galatasaray-Barcelona y se comparó la pestaña 1X2 con la pestaña "Ambos equipos marcan" (BTTS) en el momento
del hallazgo. La tabla 1X2 mostraba bet365 con cuota "1" (victoria local) = 8.00 y Retabet con cuota "X"
(empate) = 5.85 — **exactamente** los mismos dos números que el scraper había guardado como BTTS
`Yes: bet365 @8.00` / `No: retabet @5.85`. La cabecera de la tabla sí se actualiza al instante al cambiar de
pestaña, pero cada fila (casa) refresca su propia cuota de forma independiente y con retardo variable en el
propio sitio (React o similar); `providers/cuotasahora.py:_switch_market_tab` leía la tabla tras un
`wait_for_timeout(800)` fijo, que a veces cae a medio refresco: la cabecera ya dice "Yes"/"No" pero alguna
fila concreta (no siempre la misma, no siempre las mismas casas) todavía arrastra el número de la pestaña
anterior, coincidiendo por casualidad en número de columnas y colando un "margen" disparatado como si fuera
arbitraje real. No es un bug de bloqueo/geo-IP ni de la lógica de `_parse_match` (que ya tenía tests
correctos con datos reales, ver `tests/test_cuotasahora_provider.py`) — es puramente un problema de timing en
el propio scraping.

**Corrección aplicada**: `_switch_market_tab` ya no espera un tiempo fijo — llama a
`_read_table_when_stable`, que relee la tabla cada 400ms (hasta 8 intentos, ~3.2s máximo) y solo la da por
buena cuando dos lecturas consecutivas son idénticas. Verificado en vivo contra el mismo partido
(Galatasaray-Barcelona) tras el fix: BTTS ahora lee correctamente bet365 `Yes @1.50 / No @2.50` y Retabet
`Yes @1.51 / No @2.57` — coincide con los valores reales de la web y con el fixture de test ya existente
(`BTTS_TABLE` en `tests/test_cuotasahora_provider.py`, capturado en vivo el mismo día). Suite de tests
completa (24 tests) sigue en verde tras el cambio.

**Nota**: el fix vive dentro de `providers/cuotasahora.py`, en el mismo fichero que ya tenía cambios sin
commitear de una sesión anterior (los mercados BTTS/DC y Champions League descritos en README.md/checklist.md
secciones "Mercados soportados"/6) — no se ha commiteado nada de este fichero todavía, queda junto al resto
de ese trabajo pendiente de revisión y commit por el usuario.
