import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Tema (topic) del chat anterior donde se publican los avisos de surebets. Vacío = se
# manda al chat sin tema. Se crea solo la primera vez y su id se cachea en
# TELEGRAM_TOPIC_CACHE_PATH para no recrearlo en cada aviso.
TELEGRAM_TOPIC_NAME = os.getenv("TELEGRAM_TOPIC_NAME", "")
TELEGRAM_TOPIC_CACHE_PATH = os.getenv("TELEGRAM_TOPIC_CACHE_PATH", "data/notify_topic.json")
# Espaciado mínimo (segundos) entre avisos de surebet a Telegram: su flood control deja
# ~20 mensajes/minuto a un mismo grupo (1 cada 3 s), y un ciclo con muchas surebets a la
# vez las manda todas de golpe sin esto - visto en vivo el 2026-09-27: 71 surebets en un
# ciclo, 120 fallos de flood control. No es que Telegram vaya a banear el bot por un pico
# puntual, es para que los avisos lleguen de verdad en vez de fallar y quedar pospuestos
# al siguiente ciclo (ver bot/telegram_bot.py notify_opportunity).
NOTIFY_MIN_INTERVAL_SECONDS = float(os.getenv("NOTIFY_MIN_INTERVAL_SECONDS", "3"))
BANKROLL = float(os.getenv("BANKROLL", "250"))
MIN_MARGIN = float(os.getenv("MIN_MARGIN", "0.01"))
FETCH_INTERVAL_SECONDS = int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
DB_PATH = os.getenv("DB_PATH", "surebets.db")

# Una surebet solo se avisa cuando aparece en este nº de escaneos seguidos
# (equivale al filtro de "edad del arb" de BetBurger: descarta cuotas que
# parpadean un instante). 1 = avisar a la primera, sin esperar una segunda
# lectura - decisión explícita del usuario (2026-09-27): con el ciclo rápido
# cada 12 min, exigir 2 ciclos añadía hasta 12 min de latencia a surebets que
# suelen durar mucho menos que eso, así que prefiere velocidad a este filtro
# concreto. Los márgenes altos (15-25%) siguen pasando por su propia
# verificación aparte (VERIFY_MARGIN/verify_cycles en engine/quality.py y
# engine/scan.py), que esto NO desactiva - solo afecta a las surebets de
# margen normal, que antes esperaban 2 ciclos sin más motivo que este.
CONFIRM_CYCLES = int(os.getenv("CONFIRM_CYCLES", "1"))
# Los importes del reparto se redondean a múltiplos de este valor (€), para que
# las casas tarden más en limitar la cuenta. 0 = importes exactos al céntimo.
ROUND_STEP = float(os.getenv("ROUND_STEP", "5"))
# Umbrales de margen (ver engine/quality.py): por encima de WARN_MARGIN se avisa
# de "margen alto"; por encima de VERIFY_MARGIN la surebet no se descarta pero
# solo se avisa tras verificarla (segunda lectura directa en el mismo escaneo, o
# VERIFY_CYCLES escaneos seguidos si no se puede); por encima de MAX_MARGIN se
# descarta como error de datos.
WARN_MARGIN = float(os.getenv("WARN_MARGIN", "0.05"))
VERIFY_MARGIN = float(os.getenv("VERIFY_MARGIN", "0.15"))
MAX_MARGIN = float(os.getenv("MAX_MARGIN", "0.25"))
VERIFY_CYCLES = int(os.getenv("VERIFY_CYCLES", "3"))

# Escaneo en dos ritmos (ver engine/cache.py): el ciclo rápido lee las APIs
# directas y suma los comparadores desde una caché en disco; el ciclo lento
# (otra tarea programada) rota por competiciones de los comparadores durante
# SLOW_BUDGET_MINUTES y actualiza esa caché. SLOW_MAX_MATCHES limita los partidos
# leídos por competición (los más próximos primero; ~0,3 s cada uno con
# CasasDeApuestasProvider, httpx sin navegador - medido en vivo el 2026-09-28,
# ya no ~30 s de navegador como con la vieja CuotasAhoraProvider, retirada
# 2026-09-27). Lo cacheado más viejo que COMPARATOR_MAX_AGE_HOURS deja de usarse.
COMPARATOR_CACHE_PATH = os.getenv("COMPARATOR_CACHE_PATH", "cache/comparator_cache.json")
# Subidos 2026-09-28 con margen real medido en la VM: un ciclo lento completo (todas las
# competiciones, tope de 12 partidos) tardó 13 min 18 s de los 20 de presupuesto - de sobra
# para el tope de 25 (algunas competiciones grandes, p.ej. la NBA con 39 partidos listados,
# se quedaban cortando 27 partidos cada vez) más la sección de béisbol añadida el mismo día
# (providers/casasdeapuestas.py:SPORT_SECTIONS). Si el presupuesto empieza a agotarse antes
# de cubrir todas las competiciones (log "Presupuesto de tiempo agotado"), hay margen para
# subirlo más; las TOP_LEAGUES (engine/cache.py) siguen teniendo prioridad, así que un
# presupuesto corto nunca las deja sin refrescar, solo retrasa las últimas de la cola.
# SLOW_MAX_MATCHES subido 25->40 el 2026-09-29: con el tope de 25 el ciclo lento real en la
# VM terminaba las 137 competiciones en 18m33s de los 25 de presupuesto (de sobra, nunca
# llegó a agotarlo) pero seguía cortando partidos reales - comprobado en vivo contra el
# sitio: /cuotas/futbol (raíz) 36, Argentina Liga Profesional 32, UEFA Nations League 26,
# /cuotas/baloncesto (raíz) y NBA 39 cada una (tenis no tenía ninguna por encima de 25). 40
# cubre las 5 con margen; coste extra estimado ~15-20s totales (~0.3s/partido, misma medida
# que el cambio 12->25), sigue dejando de sobra los 25 min de presupuesto.
SLOW_BUDGET_MINUTES = int(os.getenv("SLOW_BUDGET_MINUTES", "25"))
SLOW_MAX_MATCHES = int(os.getenv("SLOW_MAX_MATCHES", "40"))
COMPARATOR_MAX_AGE_HOURS = float(os.getenv("COMPARATOR_MAX_AGE_HOURS", "8"))

# Máximo de proveedores CON NAVEGADOR (Chromium) leyéndose a la vez; las fuentes por httpx
# (Altenar, Kambi, Bet777...) no cuentan y arrancan siempre todas a la vez. Vacío/0 = automático:
# nº de CPUs + 1 (3 en la VM de 2 vCPU). Lanzar los ~10 navegadores a la vez satura la CPU y
# varios acaban con timeout aunque cada uno por separado funcione bien (VM: load average >10);
# hasta el 2026-09-28 lo limitaba, sin querer, el pool de hilos por defecto de asyncio (6 hilos,
# compartidos con las fuentes por httpx). Un valor negativo = sin límite. Ver engine/scan.py:_call.
_fetches = int(os.getenv("MAX_CONCURRENT_FETCHES", "0"))
MAX_CONCURRENT_FETCHES = _fetches if _fetches > 0 else None if _fetches < 0 else (os.cpu_count() or 2) + 1

# "Aparcar" las fuentes de navegador que fallan o vienen vacías N ciclos seguidos (ver
# engine/health.py): se saltan y se reintentan cada vez más espaciadas (30 min ... 6 h), y una
# lectura buena las recupera. 0 = desactivado (se leen todas siempre). El estado va en cache/
# (fuera de git), propio de cada máquina.
SOURCE_PARK_AFTER = int(os.getenv("SOURCE_PARK_AFTER", "5"))
SOURCE_HEALTH_PATH = os.getenv("SOURCE_HEALTH_PATH", "cache/source_health.json")
# Partidos que listaban las demás casas en el ciclo anterior, para adelantar la segunda pasada de
# PokerStars (engine/peers.py). Fuera de git, propio de cada máquina.
PEER_EVENTS_PATH = os.getenv("PEER_EVENTS_PATH", "cache/peer_events.json")

# Betfair Exchange API oficial (ver providers/betfair_exchange.py), aparte del
# scraper DOM de la web de apuestas fijas (providers/betfair.py). Opcional: sin
# estas tres variables el provider se salta solo, sin romper el escaneo. La app
# key se genera gratis en developer.betfair.com (Delayed App Key, sin coste de
# activación); usuario/contraseña son los de tu cuenta normal de Betfair.
BETFAIR_APP_KEY = os.getenv("BETFAIR_APP_KEY", "")
BETFAIR_USERNAME = os.getenv("BETFAIR_USERNAME", "")
BETFAIR_PASSWORD = os.getenv("BETFAIR_PASSWORD", "")
# Comisión que Betfair retiene sobre las ganancias netas de cada mercado (no se
# resta del precio que se ve en pantalla, solo de lo que realmente cobras): sin
# descontarla, la cuota "a favor" del Exchange parecería mejor de lo que es de
# verdad para el arbitraje. 0.05 = 5%, la tarifa por defecto habitual; ajústala
# si tu cuenta tiene una comisión distinta (Betfair la muestra en "Mi cuenta").
BETFAIR_EXCHANGE_COMMISSION = float(os.getenv("BETFAIR_EXCHANGE_COMMISSION", "0.05"))
