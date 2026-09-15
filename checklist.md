# Checklist

Contexto (actualizado 2026-09-16): este documento se creó originalmente pensando solo en Bigwin/Bet365,
antes de probar nada en vivo. Desde entonces se ha probado con Playwright real, en vivo, una veintena de
casas DGOJ. Este documento ahora recoge el resultado real de todas ellas, unificado en un solo sitio (antes
parte de esta info vivía también en el README). Corrección importante sobre el contexto original: Kirolbet
**no** quedó resuelto como decía la primera versión de este checklist — está bloqueado por Akamai (ver
sección 0).

## 0. Resultado verificado en vivo (no teórico) — 2026-09-16

**Funcionan (3, integradas en `main.py`):**

| Casa | Provider | Notas |
|---|---|---|
| Sportium | `providers/sportium.py` ✅ | Playwright headless normal, sin trucos. 1X2 verificado. Over/under pendiente (línea y cuota concatenadas en el mismo texto del DOM). |
| Betfair | `providers/betfair.py` ✅ | Playwright headless normal. 1X2 verificado sobre el listado completo de LaLiga. |
| Winamax | `providers/winamax.py` ✅ | Playwright headless normal. Cuotas en coma decimal española, convertidas a float. |

**Bloqueadas (con causa técnica confirmada):**

| Casa | Causa | Detalle |
|---|---|---|
| Kirolbet | Akamai Bot Manager | API JSON (`/Api/esp/Lib/Competicion`) ya localizada y parseada en `providers/kirolbet.py`, pero Akamai devuelve 403 incluso con `fetch()` real ejecutado dentro de la página — detecta el propio Chromium automatizado (fingerprint), no solo el patrón de la petición. |
| Bwin | reCAPTCHA Enterprise invisible | Se dispara nada más entrar y bloquea la petición que trae los datos del widget de cuotas. |
| Betsson | API antifraude propia | 403 en `/api/fraud/v1/groupib/tokens/generate`, antes de poder pedir cuotas. |
| Codere | Bloqueo de red | Denegación directa, sin completar el intercambio HTTP normal desde el entorno de pruebas (cloud). |
| Suertia (OlyBet) | Bloqueo de red | "Access Denied" servido por el proveedor de infraestructura, mismo patrón que Codere. |
| bet365 | Anti-bot agresivo | Spinner de carga infinito con cualquier navegador automatizado; nunca renderiza cuotas. Es la protección más dura de todas las probadas. |
| Marca Apuestas | Cloudflare / API propia | Challenge "Just a moment..." o 403 directo en `sportswidget.../refresh-bets`. |
| Luckia | Cloudflare | Challenge JS "Just a moment...". |
| Interwetten | Cloudflare | Challenge JS "Just a moment...". |
| William Hill | Bloqueo de IP explícito | La web devuelve literalmente el mensaje "Data Centre block" — es el único bloqueo que se declara a sí mismo como por rango de IP, no por fingerprint. |

**Sin confirmar (candidatas a re-probar primero, sin bloqueo aparente):**

Paston, 888sport, PokerStars Sports, Zebet, Botemanía — cargaron sin 403/Cloudflare/CAPTCHA visible, pero no
se llegó a localizar con certeza el contenedor DOM real de la tabla de cuotas en el tiempo dedicado a cada
una. Es el trabajo pendiente más rentable: no requieren ninguna técnica especial, solo más tiempo de
inspección (y comprobar si cargan las cuotas vía XHR/JSON, que sería más fácil de parsear que el DOM, como
pasa con Kirolbet).

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
- [ ] Evaluar APIs de cuotas de terceros (The Odds API, OddsJam, Pinnacle API) — no evaluado en detalle;
      vía legítima y estable si el sistema crece, evita pelear con anti-bot caso por caso, pero tiene coste
      mensual.
- [ ] Comparadores públicos (oddsportal.com, oddschecker) como contraste manual — no usado todavía.
- [ ] Programas de afiliados con datafeed oficial (XML/JSON) de alguna de las casas bloqueadas — no
      investigado para ninguna.
- [ ] Herramientas SaaS de arbitraje (RebelBetting, BetBurger) como alternativa de pago al scraping propio —
      no evaluado.
- [x] Documentar qué casas quedan cubiertas por scraping propio y cuáles no — hecho en README.md
      ("Estado real de los scrapers") y en este checklist (sección 0).
