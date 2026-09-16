"""Un solo ciclo de escaneo, pensado para correr como job programado de GitHub
Actions (ver .github/workflows/scan.yml) en vez de como proceso de larga duración.

Diferencia clave con main.py: aquí no hay proceso continuo ni Application de
python-telegram-bot con polling (no hace falta para solo enviar avisos), y el
estado de "oportunidades activas" para el dedupe se carga/guarda en un JSON en
disco (data/active_opportunities.json) porque cada ejecución de Actions es un
runner nuevo que no recuerda nada del anterior; ese JSON se commitea de vuelta
al repo al final del workflow.

Efecto colateral de este modo "solo avisos": los comandos /hoy, /ahora y
/stats del bot (bot/telegram_bot.py) no responden aquí, porque necesitan un
proceso escuchando permanentemente los mensajes de Telegram. Documentado en
deploy/README_DEPLOY.md.

Al final de cada ciclo también vuelca el estado a docs/data.json (ver
storage.db.export_snapshot), que el workflow commitea junto al resto y que
alimenta el panel web estático servido por GitHub Pages desde docs/.
"""

import asyncio
import json
import logging
import pathlib

from telegram import Bot

import config
from engine.scan import run_scan_cycle
from providers.base import OddsProvider
from providers.betfair import BetfairProvider
from providers.cuotasahora import CuotasAhoraProvider
from providers.sportium import SportiumProvider
from providers.winamax import WinamaxProvider
from storage.db import export_snapshot, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("surebets.action")

PROVIDERS: list[OddsProvider] = [
    SportiumProvider(),
    BetfairProvider(),
    WinamaxProvider(),
    CuotasAhoraProvider(),
]
SPORTS = ["futbol", "futbol_champions"]

STATE_PATH = pathlib.Path("data/active_opportunities.json")
SNAPSHOT_PATH = pathlib.Path("docs/data.json")


async def main() -> None:
    pathlib.Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.DB_PATH)

    active_state: dict[str, float] = {}
    if STATE_PATH.exists():
        active_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    bot = Bot(config.TELEGRAM_BOT_TOKEN)

    async def notify(text: str) -> None:
        if config.TELEGRAM_CHAT_ID:
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)

    await run_scan_cycle(
        PROVIDERS,
        SPORTS,
        config.BANKROLL,
        config.MIN_MARGIN,
        config.DB_PATH,
        active_state,
        notify=notify,
        logger=logger,
    )

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(active_state, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot = export_snapshot(config.DB_PATH)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
