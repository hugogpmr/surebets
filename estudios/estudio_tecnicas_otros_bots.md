# Estudio: cómo consiguen otros bots de surebets cubrir tantas casas (y qué nos queda por probar)

Fecha: 2026-09-23. Motivación: el usuario pide investigar en profundidad cómo bots/escáneres de arbitraje
de terceros (RebelBetting, BetBurger, Surebet.com, OddsJam...) consiguen datos de casas que aquí siguen
bloqueadas (bet365, William Hill, Codere, Marca Apuestas, Betsson, Luckia, Suertia/OlyBet, Retabet...), y
qué ideas nuevas —compatibles con el veto explícito a evasión activa de `checklist.md` §3— no se han probado
todavía.

**Método**: búsqueda web (documentación oficial, foros, repos GitHub de scrapers de bet365, comparativas de
APIs de cuotas) + contraste con lo ya verificado en vivo en este repo (`checklist.md`, memoria del proyecto,
`estudio_casas_faltantes.md`). No se ha implementado nada todavía; esto es solo diagnóstico + propuesta,
igual que los estudios anteriores.

## 1. La verdad incómoda primero: cómo lo hacen realmente los bots comerciales grandes

Antes de buscar "trucos", vale la pena ser honesto sobre lo que de verdad hay detrás de escáneres como
RebelBetting/BetBurger/Surebet.com/OddsJam, porque cambia las expectativas de lo que es replicable gratis:

1. **Pagan feeds B2B directos** (OddsMatrix/EveryMatrix, BetConstruct, Sportradar, FeedConstruct) o acuerdos
   comerciales con las propias casas. Esto es lo que ya se descartó en
   [Métodos para obtener cuotas...](<Métodos para obtener cuotas deportivas en tiempo real  scraping vs APIs agregadas vs feeds.md>):
   cientos/miles de €/mes, perfil de negocio con monetización, no de proyecto personal.
2. **Cuando scrapean, lo hacen con infraestructura que aquí está vetada a propósito**: granjas de proxies
   residenciales/móviles rotativos, `playwright-stealth`/fingerprint spoofing, y en algunos casos cientos de
   cuentas reales o extensiones de navegador instaladas por usuarios voluntarios que "donan" su sesión ya
   logueada (el origen histórico de herramientas como OddsJam/RebelBetting fue justo eso: una extensión de
   Chrome que el propio usuario instala en su cuenta real, no un bot en un datacenter). Es la explicación real
   de "cómo consiguen bet365" que buscaba la pregunta: mayoritariamente evasión activa a escala, no un
   endpoint secreto. Esto confirma que el veto ya decidido en este proyecto (`checklist.md` §3) es precisamente
   la línea que separa este proyecto de esas herramientas — no hay atajo gratis que lo sustituya sin cruzar esa
   línea.
3. Dicho esto, **hay un tercer grupo de trucos que SÍ son scraping/consumo normal (sin evasión) y que este
   proyecto no ha agotado todavía** — son el resto de este documento.

## 2. Ganancia rápida y gratis: Betfair Exchange API oficial (no probado, alto valor)

Hallazgo nuevo de esta investigación, no mencionado en estudios previos: **Betfair tiene una API REST +
streaming oficial y gratuita para uso no comercial**, separada de la web de apuestas fijas que hoy scrapea
`providers/betfair.py`.

- **Delayed Application Key: gratis, sin coste de activación**, con delay variable de 1-180s y sin volumen
  emparejado visible — de sobra para arbitraje pre-partido (no in-play de milisegundos, que es justo el foco
  de este proyecto según `user_goals_and_style`). El Live App Key sí cuesta una activación de pago (~499£),
  pero solo hace falta para apostar de verdad vía API, no para leer precios.
- Es un **canal completamente oficial y soportado** (developer.betfair.com), cero riesgo de baneo, cero
  evasión — lo opuesto a scrapear el DOM de la web de apuestas fijas de Betfair, que es justo lo que hoy da
  problemas (geo-IP en runners cloud, cambios de DOM ya parcheados dos veces según la memoria del proyecto).
- **Qué añade de verdad**: los precios back/lay del Exchange no son "cuotas de una casa" en el sentido
  clásico, pero sirven de dos formas: (a) como referencia "sharp" adicional para el filtro de coherencia de
  `engine/quality.py` (detectar cuotas atípicas de otras casas comparándolas contra el Exchange, que suele ser
  el mercado más eficiente); (b) para arbitraje real "back-lay" (apostar a favor en una casa normal y en
  contra en el Exchange), la técnica clásica de "matched betting", que es un tipo de oportunidad que este
  sistema hoy no contempla en absoluto (`engine/scan.py` solo cruza cuotas back entre casas).
- **Coste de implementación**: medio. Hay que registrar una app key (gratis, proceso online) y usar el SDK
  oficial o llamadas REST directas (hay ejemplos Python oficiales en `github.com/betfair-datascientists/API`).
  No sustituye necesariamente al scraper DOM actual de Betfair (ese ya funciona y es gratis), pero es un canal
  paralelo mucho más robusto que merece evaluarse como reemplazo si el DOM sigue dando problemas de geo-IP.

**Implementado 2026-09-23** (`providers/betfair_exchange.py`, registrado en `direct_providers()`, con tests
unitarios de todo el parseo): login interactivo (usuario+contraseña+app key, no el login por certificado) +
JSON-RPC contra `listCompetitions`/`listMarketCatalogue`/`listMarketBook`. Solo 1X2 de LaLiga por ahora. La
cuota que guarda ya descuenta `config.BETFAIR_EXCHANGE_COMMISSION` (5% por defecto) de la ganancia neta, para
no inflar el margen calculado frente a una casa normal. **Sin verificar en vivo, a diferencia de todo lo
demás de este repo**: no hay forma de generar una app key/cuenta de Betfair en nombre del usuario, así que el
único paso que falta es que el propio usuario la genere en developer.betfair.com y la pegue en `.env`
(`BETFAIR_APP_KEY`/`BETFAIR_USERNAME`/`BETFAIR_PASSWORD`) — sin esas tres variables el provider se salta solo,
confirmado con un test, así que no rompe el escaneo mientras tanto. Pendiente de una sesión futura: correr
`fetch_markets(["futbol"])` una vez con credenciales reales y corregir lo que la documentación oficial de
Betfair no deje ver (nombres de runner que no coincidan con el evento, límites de sesión del login
interactivo, etc.) — el ángulo "back-lay" (matched betting) sigue sin implementar, solo se usa el precio a
favor (back) como si fuera la cuota de una casa normal.

## 3. Extender el truco que YA funciona aquí: encontrar la plataforma blanca de cada casa bloqueada

Esta es, de lejos, la fuente de mayor cobertura que este proyecto ya ha explotado con éxito (Altenar,
Kambi, Sportify/FeedConstruct para bet777) y **no se ha aplicado sistemáticamente a las casas que hoy
siguen bloqueadas por scraping directo**. La idea: la mayoría de casas de apuestas de tamaño medio no
construyen su propia plataforma de cuotas — la alquilan a un proveedor B2B (Altenar, Kambi, EveryMatrix/
OddsMatrix, Digitain, BetConstruct, SBTech, Betradar/Sportradar MTS...), y ese proveedor a menudo expone un
JSON público sin autenticación pensado para que el frontend de la casa lo consuma, sin el mismo nivel de
protección anti-bot que la marca "insignia" del grupo (que sí es plataforma propia y cara de proteger, como
bet365 o Kirolbet/Akamai).

**Cómo se hizo con Speedybet (memoria 2026-09-21)**: no se adivinó el código de casa, se leyó el tráfico de
red real de la web pública para encontrar `pafspeedybetes` en la URL de Kambi. Ese mismo método —abrir la web
de la casa bloqueada, mirar la pestaña Red del navegador (o del Browser pane) y ver a qué dominio de
terceros llama para pedir cuotas— no se ha aplicado todavía, que se sepa, a:

- **Codere**: antes de intentar nada, sigue pendiente el paso más barato de todos (ya señalado en
  `estudio_casas_faltantes.md`): un `nslookup`/prueba de conexión simple desde el PC del usuario, porque el
  dominio ni resuelve desde dos redes distintas — puede que ni haga falta scraping.
- **William Hill** (`sports.williamhill.es`): bloqueo de IP de datacenter confirmado y ya identificado como
  la prueba más barata pendiente — falta solo ejecutarla desde la IP residencial/tarea programada del
  usuario, sin necesidad de ninguna plataforma blanca.
- **Retabet, Marca Apuestas, Suertia/OlyBet, Betsson, Luckia**: ninguna se ha auditado todavía para ver si su
  tabla de cuotas viaja por un dominio de un proveedor B2B conocido (patrones a buscar en la pestaña Red:
  `*.kambicdn.*`/`*.kambi.com`, `*.altenar.com`/`*-altenar-*`, `*.digitain.com`, `*.everymatrix.com`/
  `*oddsmatrix*`, `*.sbtech.com`, `*.sportradar.com`/`*mts*`, `*.betconstruct.com`). Si alguna resulta ser
  Altenar/Kambi/Digitain con un tenant no listado todavía, el coste de sumarla es el mismo que ya costó sumar
  `betinia`/`daznbet`/`yosportses` a `providers/altenar.py`/`providers/kambi.py`: prácticamente cero código
  nuevo, solo añadir el código de tenant correcto a una lista ya existente.
- Caso particular ya confirmado por la propia investigación de este proyecto: **bwin usa su propia API
  interna** (`cds-api/bettingoffer/fixtures`, Entain) y **ya está implementada** — es la prueba de que este
  patrón (mirar qué API interna sirve la tabla, sin necesidad de "hackear" nada) también funciona en casas que
  no son de un proveedor B2B público, solo hace falta mirar.

**Por qué merece prioridad alta**: no es una técnica nueva ni arriesgada, es literalmente repetir con
disciplina lo que ya dio los mejores resultados de coste/beneficio del proyecto (Altenar/Kambi cubrieron de
golpe 7+ casas), aplicado a las 5-6 casas que faltan. Coste: una sesión de auditoría con el Browser pane por
casa (gratis), sin tocar código de scraping hasta confirmar el hallazgo.

### 3.1. Resultado de la primera auditoría (2026-09-23, Browser pane, solo lectura de red)

Hecha hoy mismo sobre las 5 casas candidatas de esta sección. Ninguna resultó ser Altenar/Kambi/Digitain con
un JSON abierto en un dominio de terceros (a diferencia de Speedybet) — pero la auditoría sí deja hallazgos
nuevos y accionables:

- **Suertia/OlyBet → confirmado: plataforma GiG Sport** (Gaming Innovation Group). La prueba es concluyente:
  `apuestas.olybet.es` carga la fuente `/fonts/icons/gig/GiGSport.ttf`, el nombre de producto real de GiG. No
  se localizó un dominio de API abierto de GiG aparte (todo viaja proxiado por `apuestas.olybet.es`, una app
  Nuxt.js), así que no es un atajo tipo Kambi/Altenar — pero sí confirma qué tecnología hay detrás, y es una
  candidata limpia a scraping DOM con Playwright normal (mismo patrón que Sportium/Betfair/Winamax): no se vio
  ningún reto Cloudflare/Akamai/reCAPTCHA al cargar.
- **Marca Apuestas → CONFIRMADO con Playwright headless real (2026-09-23), diagnóstico de `checklist.md`
  (2026-09-16) obsoleto.** Aquel decía Cloudflare + endpoint `sportswidget.../refresh-bets`; hoy
  `marcaapuestas.es` sirve un frontend completamente distinto (`no_brand_candy-theme`, endpoints propios
  `/sportsbookPostInitConf`, `/sportsbookCustomization`, `/initialResources/...`) y un
  `chromium.launch(headless=True)` normal, sin ningún truco, lo carga con **status 200, sin ningún marcador de
  reto (Cloudflare/Akamai/reCAPTCHA), y con cuotas reales visibles en el DOM** (17 valores tipo `1.02`, `4.50`,
  `26.00`... extraídos con una regex simple tras aceptar cookies). **Candidata real y verificada a nuevo
  provider Playwright**, mismo patrón que Sportium/Betfair — pendiente solo de mapear los selectores CSS
  exactos del listado de partidos/mercados antes de escribir `providers/marcaapuestas.py`.
- **Retabet → sigue bloqueado, la auditoría de hoy fue redundante (corrección).** Al revisar la memoria del
  proyecto tras la auditoría por Browser pane (sección 3.1 original de este documento decía "nunca se había
  probado", que era **incorrecto**): la memoria del 2026-09-21 ya documentaba `Retabet = 403 "Error de
  seguridad"` con Playwright headless plano. Se repitió la prueba hoy (headless real, sin trucos) contra
  `apuestas.retabet.es/deportes/futbol/1` y **se reprodujo exactamente el mismo bloqueo**: `403`, título
  "Error de seguridad", mismo texto de la página de error con referencia de soporte. Confirma que, a
  diferencia de Marca Apuestas, aquí el diagnóstico antiguo seguía vigente — el "carga bien en el Browser
  pane" fue, una vez más, un falso positivo (la misma lección de Interwetten). Se descarta como candidata.
- **Betsson → sigue confirmado bloqueado, sin cambios ni atajo nuevo.** Se ve literalmente la llamada
  `POST /api/fraud/v1/groupib/tokens/generate` que ya documentaba `checklist.md` — es el producto antifraude
  de **Group-IB** (empresa de ciberseguridad dedicada a esto, no un WAF genérico), y sigue disparándose antes
  de poder pedir cuotas. No hay plataforma blanca que rodear aquí.
- **Luckia → el portal/CMS sigue tras Cloudflare Bot Management** (`cdn-cgi/challenge-platform/h/b/scripts/
  jsd/...`, el script real de "JS Detection" de Cloudflare), consistente con el diagnóstico ya conocido. Esta
  auditoría solo miró la home (Liferay/CMS de marketing); no se llegó a entrar en la plataforma de apuestas
  real (probablemente un subdominio aparte, como pasó con William Hill) — pendiente si se quiere insistir.

**Siguiente paso concreto para las dos candidatas nuevas (Retabet y Marca Apuestas)**: confirmar con
`chromium.launch(headless=True)` real (no solo Browser pane) antes de escribir ningún provider, exactamente
la misma disciplina que ya evitó un falso positivo con Interwetten.

**Actualizado 2026-09-23 (tarde), ya implementado**: confirmado con Playwright headless real. Retabet
reprodujo el mismo `403 "Error de seguridad"` ya conocido (descartada, la auditoría de por la mañana fue un
falso positivo del Browser pane). **Marca Apuestas cargó limpio (status 200, sin reto, cuotas reales en el
DOM)** — inspeccionado el DOM con JavaScript en vivo y confirmado que usa exactamente el mismo framework
"ta-" que Sportium, con los mismos códigos internos de mercado (`BTSC`=Ambos Marcan, `H1RS`=Resultado al
descanso, `MRES`=1X2). Implementado como `providers/marcaapuestas.py` (copia adaptada de
`providers/sportium.py`, sin Doble Oportunidad porque esta casa no la tiene en su desplegable), con tests
contra datos reales capturados en vivo, registrado en `direct_providers()`
(`scripts/scan_once_action.py`), licencia DGOJ comprobada en `ordenacionjuego.es` (Casino Marbella
Interactive, S.A.) y añadido a `docs/app.js` (`DGOJ_LICENSED_BOOKMAKERS`/`BOOKMAKER_URLS`). Smoke test en
vivo: 40 mercados (10 partidos × 1X2/BTTS/1X2_HT/OU) extraídos correctamente contra Primera División.

## 4. Más comparadores/agregadores "abiertos" además de CuotasAhora y BetExplorer (no probados)

CuotasAhora ya demostró que un comparador sin anti-bot puede desbloquear de golpe media docena de casas.
Hay más comparadores/agregadores con vocación pública (viven de que los vea gente y afiliados, no de vender
API cara) que no se han evaluado todavía:

- **Oddspedia** (`widgets.oddspedia.com` / `oddspedia.com`): se anuncia como widgets **y API completamente
  gratis, sin límites de paquete**, pensados para que cualquier publisher los incruste. **Descartada,
  confirmado 2026-09-23 con Playwright headless real**: a diferencia de Marca Apuestas, aquí sí es un bloqueo
  de verdad — `chromium.launch(headless=True)` sin ningún truco recibe el challenge JS real de Cloudflare
  ("Just a moment...", `403`) en las dos URLs probadas (`oddspedia.com` y `widgets.oddspedia.com`), no un falso
  positivo de un fetch sin navegador. Seguirla requeriría stealth/evasión, que sigue vetado — se cierra esta
  vía sin más inversión.
- **OddsGuard** (`oddsguard.com/widgets`): widgets de cuotas en tiempo real "gratis" declarados para 72 casas,
  pensados para incrustar vía iframe con un `affiliateId`. Mismo patrón de verificación: probar con Playwright
  real si el iframe carga sin necesitar registro previo del dominio embebedor (algunos widgets de afiliados sí
  exigen whitelisting de dominio, lo que lo invalidaría para uso local/scraping).
- **EnetOdds**: se posiciona como proveedor de feeds XML/API "a editores" desde 25+ casas — perfil más B2B que
  Oddspedia/OddsGuard, revisar condiciones de acceso antes de invertir tiempo.
- **oddsportal.com directamente** (mismo grupo que cuotasahora.com, la versión española): no evaluado todavía
  como fuente independiente — podría tener más casas/mercados que la versión .es, aunque su API interna
  también está cifrada según lo ya documentado (se resuelve igual: leer el DOM ya descifrado por el propio
  navegador, no la API cifrada).

**Precaución compartida con CuotasAhora**: cualquier comparador nuevo necesita la misma verificación de
licencia DGOJ por casa mostrada (`ordenacionjuego.es`) antes de sumar una casa nueva al panel, y el mismo
filtro para no duplicar una casa que ya se scrapea en directo (regla `ALLOWED_BOOKMAKERS` que ya existe en
`providers/cuotasahora.py`).

## 5. APIs agregadas gratuitas no evaluadas todavía (complemento, no sustituto)

El documento ["Métodos para obtener cuotas..."](<Métodos para obtener cuotas deportivas en tiempo real  scraping vs APIs agregadas vs feeds.md>)
ya evaluó Odds-API.io, SharpAPI y OddsPapi. Dos más aparecidas en esta investigación, con matices:

- **pinnapi** (Pinnacle): **100 requests/día gratis, sin tarjeta**, latencia muy baja (push, no polling).
  Pinnacle no es una casa DGOJ y su cobertura de ligas menores es floja, así que no sirve para arbitrar
  directamente contra las casas españolas de este proyecto — pero es la referencia "sharp" por excelencia del
  sector (el libro más eficiente del mundo), útil como segunda señal de coherencia en `engine/quality.py`
  (mismo rol que se propone para Betfair Exchange en la sección 2), gratis y sin scraping.
- **SportsGameOdds**: free tier declarado, sin verificar en detalle cobertura española — de menor prioridad,
  pendiente de auditar si se quiere ampliar la lista de candidatas.
- Nota importante: la propia investigación confirma que **Pinnacle cerró su API pública a nuevos usuarios en
  julio de 2025** (acceso ahora por solicitud a `api@pinnacle.com` para casos de uso académicos/apostadores de
  alto volumen) — la vía práctica gratuita hoy es un intermediario como pinnapi, no Pinnacle directamente.

## 6. Zona gris a discutir antes de tocar (no implementar sin decisión explícita)

Dos ideas que aparecen mucho en foros de arbitraje pero que rozan o cruzan la línea ya vetada en
`checklist.md` §3 — se documentan para que quede constancia de que se investigaron, no como recomendación de
implementarlas:

- **API de la app móvil oficial en vez de la web**: una app nativa no puede ejecutar el reto JS de
  Cloudflare/Akamai que sí frena a un navegador automatizado, así que algunas apps hablan con un backend con
  menos fricción de fingerprinting (aunque a veces compensan con firma HMAC de las peticiones o certificate
  pinning). Observar el tráfico de tu propio teléfono con tu propia cuenta (p. ej. con un proxy como mitmproxy)
  no es "hackear" nada, pero **replicar después esa firma/autenticación para hacerse pasar por la app oficial
  sí empieza a ser evasión de un control puesto a propósito** — misma categoría que `playwright-stealth`, y
  por tanto misma regla: no se toca sin hablarlo contigo antes.
- **Fuentes "parásitas" de otros bots gratuitos** (canales/grupos públicos de Telegram u otros que publican
  ya sus propias oportunidades de arbitraje en el tier gratis, como leads o gancho de venta de su plan de
  pago): el repo ya tiene infraestructura de Telegram (`telegram_source/relay.py`) aunque hoy se usa solo para
  reenviar los propios avisos a un grupo (ver memoria `project_notify_routed_to_relay_group`), no para
  consumir datos ajenos. Técnicamente trivial de extender (suscribirse a un canal público y parsear su texto),
  pero con problemas reales de fiabilidad (no se controla la calidad/frescura/veracidad de una cuota que
  publica un tercero) y de zona gris de términos de servicio de ese tercero — se deja aquí solo como opción
  conocida, de menor prioridad que las técnicas 2-5 porque esas sí dan datos de fuente primaria verificable.

## 7. Qué no vamos a intentar (y por qué, para que quede explícito una vez más)

Confirmación de lo ya decidido en `checklist.md` §3, ahora con el contexto de por qué es precisamente lo que
usan los bots comerciales grandes para cubrir bet365/Akamai/reCAPTCHA:
`playwright-stealth`/fingerprint spoofing, proxies residenciales o móviles de pago, farms de IPs rotativas, y
login con cuentas reales para "relajar" un WAF. Todo sigue vetado sin discutirlo contigo antes — el riesgo no
es solo técnico, es de cierre de cuentas reales de apuestas.

## 8. Recomendación de orden de trabajo (coste/beneficio, de más a menos inmediato)

1. **Auditoría de plataforma blanca** (sección 3) en Retabet, Marca Apuestas, Suertia, Betsson, Luckia — solo
   Browser pane + pestaña Red, gratis, puede desbloquear varias casas de golpe igual que Altenar/Kambi.
2. **Ejecutar la prueba pendiente desde el PC del usuario** (bet365 y William Hill vía IP residencial) —
   ya diagnosticada en `estudio_casas_faltantes.md`, solo falta correrla; es la de mayor probabilidad de éxito
   inmediato de todo este documento.
3. **`nslookup`/conexión simple a Codere desde el PC del usuario** — dos minutos, puede que no sea ni un
   problema de scraping.
4. ~~Probar Oddspedia con Playwright headless real~~ **Descartada 2026-09-23**: bloqueo real de Cloudflare
   confirmado (ver sección 4), no un falso positivo. Cerrada sin más inversión.
5. **Betfair Exchange API oficial** (sección 2) — coste de implementación algo mayor (SDK/REST + registro de
   app key), pero es la única opción 100% oficial y sin ningún riesgo de bloqueo de todo este documento; buen
   candidato si se quiere robustecer el proveedor Betfair actual o añadir el ángulo "back-lay" nuevo.
6. **pinnapi como señal de coherencia adicional** (sección 5) — barato, pero es una mejora de calidad del
   filtro de `engine/quality.py`, no de cobertura de casas españolas nuevas.
