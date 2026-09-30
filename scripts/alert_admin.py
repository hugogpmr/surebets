"""Manda un aviso al canal privado de administración (config.ADMIN_ALERT_CHAT_ID).

    python scripts/alert_admin.py "texto del aviso"   # lo manda
    python scripts/alert_admin.py --discover          # lista los chats donde el bot ha recibido algo

Lo usan deploy/vm_fast_scan.sh y vm_slow_scan.sh cuando un ciclo termina con error (p.ej. el
kernel mata el proceso por falta de memoria), que el propio escaneo no puede avisar porque ya no
está vivo. `--discover` sirve para averiguar el id del canal: añade el bot como administrador,
publica cualquier mensaje en el canal y ejecútalo.
"""

import asyncio
import pathlib
import sys

# Ejecutado como `python scripts/alert_admin.py`, la carpeta del proyecto no está en sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from telegram import Bot  # noqa: E402

import config  # noqa: E402
from bot.telegram_bot import notify_admin  # noqa: E402


async def discover(bot: Bot) -> None:
    seen: dict[int, str] = {}
    for update in await bot.get_updates(timeout=0, allowed_updates=["message", "channel_post", "my_chat_member"]):
        chat = (update.effective_chat)
        if chat is not None:
            seen[chat.id] = f"{chat.type}: {chat.title or chat.username or chat.first_name}"
    if not seen:
        print("Sin chats: publica un mensaje en el canal (con el bot ya de administrador) y repite.")
    for chat_id, label in seen.items():
        print(f"{chat_id}  {label}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    bot = Bot(config.TELEGRAM_BOT_TOKEN)
    if sys.argv[1] == "--discover":
        asyncio.run(discover(bot))
    else:
        asyncio.run(notify_admin(bot, " ".join(sys.argv[1:])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
