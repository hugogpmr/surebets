import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BANKROLL = float(os.getenv("BANKROLL", "250"))
MIN_MARGIN = float(os.getenv("MIN_MARGIN", "0.01"))
FETCH_INTERVAL_SECONDS = int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
DB_PATH = os.getenv("DB_PATH", "surebets.db")
