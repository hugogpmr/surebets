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
