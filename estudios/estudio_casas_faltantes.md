> **Actualización 2026-09-23**: PokerStars y **William Hill** ya están implementados
> (`providers/pokerstars.py`, `providers/williamhill.py`, ✅ en README/checklist.md). **bet365 se
> probó de verdad (Playwright headless real, desde este sandbox Y desde el PC del usuario con IP
> residencial) y sigue bloqueado por Cloudflare en los dos sitios** — a diferencia de lo que sugería
> este estudio, el bloqueo NO es solo de IP de datacenter/VPN, persiste incluso con navegador
> automatizado real desde casa. Se descarta por ahora (no se toca stealth/evasión). Aviso que ya quedó
> registrado en memoria del proyecto: **Interwetten**, que este documento daba casi por seguro tras
> cargar bien en el Browser pane, resultó seguir bloqueada por Cloudflare en Playwright headless real
> en los mismos dos entornos — "carga bien en el Browser pane" no es garantía de que un headless normal
> también pase el control, hace falta la prueba real antes de dar nada por bueno (así se confirmaron
> tanto PokerStars como William Hill: con Playwright headless real, no solo con el Browser pane).
> Para William Hill el plan también cambió sobre la marcha: en vez de necesitar la IP residencial del
> usuario para el scraping en sí, resultó que solo la *web* está bloqueada por IP — su API JSON
> responde igual desde cualquier sitio, incluido este sandbox, así que el provider final ni siquiera
> necesita ejecutarse desde el PC del usuario.
>
> **Actualización 2026-09-24 — Codere, cerrado (sin éxito, mismo motivo que Kirolbet)**: la web de
> marketing (`www.codere.es`) carga perfectamente (el "bloqueo de red"/DNS de la sección 4 de abajo
> resultó ser la VPN del propio usuario, no del dominio). Pero la plataforma real de apuestas vive en
> otro subdominio, `m.apuestas.codere.es` (un SPA con hash-routing), y ese subdominio está protegido
> por **Akamai Bot Manager**: "Access Denied" tanto al navegar directo como reusando en la misma sesión
> las cookies de sensor de Akamai (`bm_sz`/`_abck`) ya plantadas por `www.codere.es` — probado desde la
> IP residencial del usuario, no solo desde este sandbox. Mismo nivel de bloqueo que Kirolbet
> (`providers/kirolbet.py`), la protección más dura ya documentada en este proyecto. Se cierra aquí sin
> implementar nada nuevo: sigue cubierta indirectamente vía CuotasAhora/BetExplorer, como ya estaba.

# Estudio: cómo sacar las cuotas de las casas que aún faltan (menor coste posible)

Fecha del estudio: 2026-09-22. Foco: las 4 casas del objetivo original (`user_goals_and_style`) que
hoy no tienen ninguna fuente propia — **bet365, William Hill, Codere, PokerStars** — más un apunte
sobre Zebet, que ya estaba identificada como candidata pero sin implementar. Todo lo de abajo es
verificación **en vivo hoy** (Browser pane real + una prueba con `httpx` desde este mismo sandbox),
no teoría ni repetición de lo que ya decía `checklist.md`/`README.md` — de hecho corrige varios
diagnósticos antiguos, igual que pasó el 2026-09-21 con Interwetten/Zebet (ver memoria del proyecto:
un 403 probando en frío no significa que el sitio esté bloqueado de verdad).

**Regla de coste aplicada**: se ordena todo por coste combinado (ingeniería + dinero + riesgo de
cuenta/ban), no solo por dificultad técnica. Ninguna opción de aquí implica stealth/evasión activa
(playwright-stealth, fingerprint spoofing) ni proxies de pago — eso sigue vetado sin hablarlo antes
contigo (`checklist.md` sección 3). Si alguna vía barata de verdad solo funciona con eso, se marca
explícitamente y se deja pendiente de tu decisión, no se implementa.

## Resumen: qué hacer primero

| Prioridad | Casa | Coste real | Resultado |
|---|---|---|---|
| 1 | **PokerStars Sports** | Gratis. `providers/pokerstars.py` (Playwright headless, DOM) | ✅ **Implementado 2026-09-23**. Su API JSON resultó estar detrás de Akamai Bot Manager (igual que Kirolbet); el DOM sí es scrapeable sin trucos, verificado con Playwright headless real. |
| 2 | **William Hill** | Gratis. `providers/williamhill.py` (API JSON, sin navegador) | ✅ **Implementado 2026-09-23**. Solo la web está bloqueada por IP de datacenter/VPN; su API responde igual desde cualquier sitio (confirmado también desde este sandbox). Ojo con el `marketType`: pedir el nombre que se ve en la web da la promo "2 Up", no el 1X2 real. |
| 3 | **bet365** | — | ❌ **Descartado por ahora**. El bloqueo de Cloudflare persiste con Playwright headless real, probado desde este sandbox Y desde el PC del usuario (IP residencial) el 2026-09-23. No es solo IP de datacenter como se pensaba. Sin stealth no hay vía barata conocida; no se implementa. |
| 4 | **Codere** | — | ❌ **Cerrado, sin éxito**. `www.codere.es` (marketing) carga bien — el fallo de DNS era la VPN del propio usuario. Pero la plataforma real de apuestas (`m.apuestas.codere.es`) está protegida por Akamai Bot Manager, mismo nivel que Kirolbet: "Access Denied" incluso con las cookies de sensor ya puestas, probado desde la IP residencial. Sigue solo por comparadores. |
| — | Zebet (bonus, no es una de las 4 objetivo) | Gratis, mismo patrón que Interwetten | Ya confirmado el 2026-09-21 que carga bien y tiene cuotas en el DOM (`estudio_limites_y_anulacion_casas.md`/memoria), solo falta implementarla como provider — mismo coste que Interwetten, que ya se hizo. |

## 1. PokerStars Sports — el hallazgo más barato de los cuatro

**Estado anterior**: README la marcaba como "Sin fuente" junto a Interwetten (ni comparadores ni
Altenar/Kambi la cubren). No se había probado en vivo con un navegador real, solo se asumía.

**Comprobado hoy (Browser pane, sin login)**:
- `pokerstars.es/sports/futbol/1/` carga sin ningún gate de bot (ni Cloudflare, ni reCAPTCHA visible
  en la petición de datos, solo cookies/consentimiento normales de UI). La tabla de 1X2 aparece
  completa en el DOM (LaLiga, UEFA Nations League, fútbol femenino, etc. — mismo patrón visual que
  bet365/Sportium/Betfair).
- Detrás hay una **API JSON propia sin autenticación real**: `POST /sports/web/gbp/sca/graphql` y
  `POST /sports/web/markets-updates?priceHistory=1`, ambas devuelven `200` desde una sesión anónima
  (sin cookie de login). Se probó a mano con `fetch()` dentro de la página: responde JSON limpio
  (`{"data":{"__typename":"Query"}...}`), no un challenge.
- No es Altenar/Kambi/Sportify (plataforma propia de PokerStars/Flutter, otro feed distinto), así que
  además de tapar el hueco suma diversidad de fuente para el cruce de arbitraje.

**Coste**: como Bet777 (`providers/bet777.py`) — un provider nuevo que hable esa API directamente
(más barato que scraping DOM porque no hace falta Playwright para esta casa, solo `httpx`/requests +
parsear la respuesta GraphQL). Falta por confirmar en una sesión de implementación: el esquema exacto
del `query` de GraphQL que pide las cuotas del listado (no se llegó a interceptar el payload completo
hoy, solo se confirmó que el endpoint existe y responde sin bloqueo) y si expone mercados aparte de
1X2 (corners/tarjetas, que es lo que más te interesa).

**Resultado final (2026-09-23)**: el plan de "API directa sin navegador" no sobrevivió al intentarlo —
esa misma API GraphQL/`markets-updates` resultó estar detrás de **Akamai Bot Manager** (un `fetch()` a
mano dentro de la página, misma sesión, ya daba 403 "Access Denied", igual que Kirolbet). Se pivotó a
leer el DOM con Playwright normal (como Sportium), verificado con un lanzamiento headless real (no solo
el Browser pane): 88 partidos con cuotas reales. Implementado en `providers/pokerstars.py`.

## 2. bet365 — el diagnóstico de "Cloudflare 403" ya no aplica igual

**Estado anterior** (`checklist.md`): "Anti-bot agresivo. Spinner de carga infinito con cualquier
navegador automatizado; nunca renderiza cuotas. Es la protección más dura de todas las probadas."

**Comprobado hoy — dos pruebas con resultado distinto, y la diferencia es la pista clave**:
- **Con `httpx` (sin navegador, header de User-Agent normal) desde este sandbox**: `403`, página de
  bloqueo de Cloudflare. Esto confirma que el bloqueo existe y sigue activo a nivel de red/fingerprint
  TLS — no es un falso diagnóstico como Interwetten.
- **Con el Browser pane (Chromium real, headed, otra IP/red)**: `bet365.es` carga completo, sin
  spinner infinito ni challenge — tabla de partidos, cuotas 1X2/hándicaps/totales todas visibles y
  reales (Champions League, UEFA Nations League, MLB, WNBA...) en la home.
- Las cuotas no viajan como JSON plano: se sirven vía `Api/1/Blob?...` — el formato binario/comprimido
  propio de bet365 que ya se documentaba de oídas ("reparte las cuotas por un websocket cifrado"). Es
  un formato conocido y con parsers de código abierto (varios scrapers de bet365 en GitHub lo
  documentan), no cifrado de verdad — es más bien un formato compacto propio, así que es "difícil de
  parsear", no "imposible sin romper cifrado".

**Interpretación**: el bloqueo depende del **fingerprint/tipo de cliente que hace la petición**
(datacenter + sin navegador real = bloqueado; navegador real, aunque sea automatizado, con la IP de
este Browser pane = no bloqueado), exactamente el mismo patrón que ya se demostró con Betfair y
CuotasAhora en GitHub Actions (0 datos desde el runner en la nube, funcionan perfecto desde el PC
local). La prueba que falta y que es gratis: correr Playwright normal (sin stealth, el mismo patrón
que Sportium/Betfair/Winamax) **desde la tarea programada del usuario** (IP residencial), no desde
este sandbox ni desde GitHub Actions.

**Coste si se confirma**: medio-alto en ingeniería (hay que escribir el parser del formato `Blob`, más
trabajo que un JSON normal tipo Altenar/Kambi/PokerStars), pero **cero coste de dinero/proxies** y
cero riesgo nuevo — es scraping normal desde un navegador normal, no evasión activa de nada.

**Resultado final (2026-09-23)**: la prueba pendiente se hizo, con Playwright headless real (sin
trucos) desde dos sitios — este sandbox y el PC del usuario (IP residencial de verdad). **Sigue
bloqueado por Cloudflare en los dos**: la hipótesis de "solo hace falta un navegador real, la IP de
datacenter no importa" no se sostuvo aquí (sí se sostuvo para William Hill, ver sección 3). Se descarta
por ahora — no hay vía barata sin tocar stealth/evasión, que sigue vetado.

## 3. William Hill — el bloqueo es real pero solo en la plataforma de cuotas

**Estado anterior** (`checklist.md`): "Bloqueo de IP explícito. La web devuelve literalmente el
mensaje 'Data Centre block'."

**Comprobado hoy**:
- `williamhill.es` (la web de marketing/registro) **carga perfectamente** desde el Browser pane, sin
  ningún bloqueo — footer, licencia DGOJ, links, todo normal.
- Al seguir el link real "Apuestas Fútbol" de esa misma página, redirige a `sports.williamhill.es`
  (la plataforma de apuestas de verdad, sub dominio aparte) — **ahí sí aparece literalmente el título
  "William Hill - Data Centre block"**. Confirma que `checklist.md` iba bien encaminado, pero afina el
  diagnóstico: el bloqueo está específicamente en `sports.williamhill.es`, no en todo el dominio, y es
  un bloqueo de **rango de IP de datacenter**, no de fingerprint de navegador (es el único de los
  cuatro que se declara explícitamente por IP, tal cual decía el checklist).

**Coste si se confirma desde el PC del usuario**: si `sports.williamhill.es` carga bien desde la IP
residencial (muy probable, dado que es un bloqueo de IP, no de comportamiento), el coste es el mismo
que Sportium/Betfair: un provider Playwright normal, cero dinero, cero riesgo nuevo. Es la prueba más
barata de las cuatro de confirmar (un solo `page.goto()` desde `scripts/local_scan.ps1` o una prueba
manual en el PC).

**Resultado final (2026-09-23), mejor de lo esperado**: se confirmó desde el PC del usuario que la web
carga bien. Pero además, capturando su tráfico de red se encontró una **API JSON propia** (plataforma
OpenBet) que **no necesita navegador ni cookies** — y que responde igual desde CUALQUIER IP, incluida
la de este sandbox (el bloqueo de IP resultó ser solo de la web, no de la API). O sea, ni siquiera hizo
falta el coste de "un provider Playwright": salió más barato todavía, un provider `httpx` puro como
Altenar/Kambi/Bet777. Único cuidado real: pedir el mercado por el nombre que se ve en la web
("Ganador del partido") da la promo "2 Up" de William Hill, no cuotas normales — el 1X2 de verdad pide
otro nombre de grupo interno. Implementado en `providers/williamhill.py`.

## 4. Codere — el problema parece ser el propio dominio, no solo la red del usuario

**Estado anterior** (`checklist.md`/memoria 2026-09-20): "Ninguno de sus dominios (codere.es,
apuestas.codere.es...) resuelve DNS desde este equipo. Pendiente de probar desde otra red."

**Comprobado hoy**: se intentó navegar a `codere.es` y `apuestas.codere.es` desde el Browser pane —
**falló también aquí**, con el mismo síntoma (no resuelve/no conecta). Esto es una red y un entorno
completamente distintos al PC del usuario, así que la hipótesis de "es solo la red de este equipo"
pierde fuerza: dos redes distintas fallando igual apunta más a un problema del lado de Codere (DNS mal
propagado, geobloqueo agresivo a nivel de resolución de nombre, o un cambio de infraestructura) que a
algo local. Las reseñas/búsquedas de hoy confirman que Codere sigue operando y con licencia DGOJ
vigente (no ha desaparecido), así que no es que la casa haya cerrado.

**Siguiente paso más barato**: probar `codere.es` desde el propio PC del usuario con un `nslookup`/
navegador normal (gratis, dos minutos) antes de dar por buena ninguna teoría — si tampoco resuelve
ahí, el candidato más probable es un bloqueo de DNS a nivel de proveedor de Internet en España (hay
precedente: algunos ISP españoles bloquean por orden judicial dominios de juego no acreditados o
listas de la DGOJ mal actualizadas) o un cambio de dominio real de Codere que no se ha detectado
todavía (revisar si usan otro dominio, p. ej. vía su app o un enlace de afiliado reciente).

**Resultado final (2026-09-24), y esta vez sin final feliz**: el "no carga" resultó ser la VPN del
propio usuario (una vez apagada, `www.codere.es` cargó perfecto — mismo tipo de falso positivo que ya
había dado este entorno con William Hill, solo que aquí era la VPN del usuario, no la de este sandbox).
Con eso resuelto, se llegó más lejos: `www.codere.es` es solo la web de marketing/SEO; la plataforma
real de apuestas (con las cuotas de verdad) vive en `m.apuestas.codere.es`, un SPA con hash-routing
(`/deportesEs/#/HomePage`) descubierto al capturar una llamada de fondo (`NavigationService/Marquee/
GetMarquee`) que la propia home dispara sola. Pero ese subdominio da **"Access Denied" de Akamai Bot
Manager** (`errors.edgesuite.net`) — probado (a) navegando directo, (b) tecleando la URL real dada por
el usuario, y (c) reusando en la misma sesión las cookies de sensor de Akamai (`bm_sz`/`_abck`) que
`www.codere.es` ya había plantado — las tres veces bloqueado, desde la IP residencial del usuario. Es
el mismo nivel de protección que ya derrotó a Kirolbet en este proyecto (la más dura documentada hasta
ahora), y ninguno de los trucos normales (sesión compartida, URL real, no solo la raíz del dominio) lo
sortea. Se cierra sin implementar nada: sigue cubierta solo por CuotasAhora/BetExplorer, como ya
estaba antes de este estudio.

## 5. Opciones descartadas o de coste demasiado alto para este proyecto

Ya evaluadas en detalle en el documento
["Métodos para obtener cuotas deportivas..."](<Métodos para obtener cuotas deportivas en tiempo real  scraping vs APIs agregadas vs feeds.md>)
(general, no específico de estas 4 casas) — resumen aplicado aquí:

- **APIs agregadas de pago** (SharpAPI, OddsPapi, The Odds API): sus free tiers no cubren bien casas
  españolas concretas como estas 4, y los planes de pago (49-79$/mes) no compensan frente a
  scraping directo gratis cuando, como se ha visto hoy, 3 de las 4 casas ni siquiera están realmente
  bloqueadas.
- **Feeds push B2B** (OddFeeds, OddsMatrix): descartados, coste de miles de €/mes, perfil de cliente
  equivocado (negocio con monetización, no proyecto personal).
- **Proxy residencial/móvil de pago**: no hace falta pagarlo todavía — el propio PC del usuario (IP
  residencial real) ya sirve de "proxy gratis" para los 3 casos donde el bloqueo es de IP/datacenter
  (bet365, William Hill, y posiblemente Codere). Solo tendría sentido si, tras probar desde el PC,
  alguna de las 4 sigue bloqueada específicamente por esa IP residencial concreta.
- **Stealth/evasión activa** (playwright-stealth, fingerprint spoofing): no se toca sin hablarlo
  contigo antes, igual que ya está decidido en `checklist.md`. No debería hacer falta para ninguna de
  las 4 si las pruebas desde el PC confirman lo de arriba.

## 6. Qué falta para pasar de "estudio" a "implementado"

**Estado final (2026-09-24) — las 4 cerradas**: 2 implementadas y en el pipeline
(`scripts/scan_once_action.py`, `DIRECT_SOURCES`), 2 descartadas por bloqueo real (no por falta de
esfuerzo):

1. ~~**PokerStars Sports**~~ ✅ hecho — `providers/pokerstars.py` (Playwright DOM, no la API, ver
   sección 1).
2. ~~**William Hill**~~ ✅ hecho — `providers/williamhill.py` (API JSON pura, ni siquiera hace falta
   navegador, ver sección 3).
3. ~~**bet365**~~ ❌ descartado — Cloudflare persiste incluso con Playwright real desde la IP
   residencial del usuario, ver sección 2. No se sigue sin hablar de stealth/evasión antes.
4. ~~**Codere**~~ ❌ descartado — Akamai Bot Manager en `m.apuestas.codere.es`, mismo nivel que
   Kirolbet, ver sección 4. Sigue solo por comparadores.

De las 4 casas objetivo de este estudio, 2 tienen ahora fuente directa nueva; las otras 2 (bet365,
Codere) están detrás de la protección anti-bot más dura que este proyecto ha encontrado (Cloudflare y
Akamai respectivamente) y se quedan fuera de alcance mientras siga vigente la política de no usar
stealth/evasión.
