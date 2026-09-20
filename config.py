import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
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
# Márgenes a partir de los cuales se avisa de "margen alto" y se descarta como
# error de datos (ver engine/quality.py).
WARN_MARGIN = float(os.getenv("WARN_MARGIN", "0.05"))
MAX_MARGIN = float(os.getenv("MAX_MARGIN", "0.15"))
