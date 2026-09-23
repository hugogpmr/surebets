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
BANKROLL = float(os.getenv("BANKROLL", "250"))
MIN_MARGIN = float(os.getenv("MIN_MARGIN", "0.01"))
FETCH_INTERVAL_SECONDS = int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
DB_PATH = os.getenv("DB_PATH", "surebets.db")

# Una surebet solo se avisa cuando aparece en este nº de escaneos seguidos
# (equivale al filtro de "edad del arb" de BetBurger: descarta cuotas que
# parpadean un instante). 1 = avisar a la primera. Con un escaneo cada ~5 min,
# 2 añade unos 5 min de latencia a cambio de menos falsos positivos.
CONFIRM_CYCLES = int(os.getenv("CONFIRM_CYCLES", "2"))
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
# leídos por competición (los más próximos; ~30 s de navegador cada uno).
# Lo cacheado más viejo que COMPARATOR_MAX_AGE_HOURS deja de usarse.
COMPARATOR_CACHE_PATH = os.getenv("COMPARATOR_CACHE_PATH", "cache/comparator_cache.json")
SLOW_BUDGET_MINUTES = int(os.getenv("SLOW_BUDGET_MINUTES", "20"))
SLOW_MAX_MATCHES = int(os.getenv("SLOW_MAX_MATCHES", "12"))
COMPARATOR_MAX_AGE_HOURS = float(os.getenv("COMPARATOR_MAX_AGE_HOURS", "8"))

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
