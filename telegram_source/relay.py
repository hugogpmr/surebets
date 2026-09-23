"""Copia los mensajes de un grupo privado a otro chat mediante un bot.

La cuenta de usuario SOLO LEE (escucha mensajes nuevos); todo lo que se publica
sale del bot. Uso:

    python -m telegram_source.relay login   # una vez: crea la sesion (codigo por Telegram)
    python -m telegram_source.relay qr      # igual, pero escaneando un QR desde el movil
    python -m telegram_source.relay topics  # lista los temas del grupo origen (id y nombre)
    python -m telegram_source.relay chats   # lista tus chats para sacar el id del grupo
    python -m telegram_source.relay run     # escucha y copia
"""
import asyncio
import io
import json
import logging
import os
import re
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("relay")

API_ID = int(os.getenv("TG_API_ID", "0") or 0)
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_PATH = os.getenv("TG_SESSION_PATH", "data/relay")
SOURCE_CHAT = os.getenv("RELAY_SOURCE_CHAT", "")
BOT_TOKEN = os.getenv("RELAY_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
TARGET_CHAT = os.getenv("RELAY_TARGET_CHAT_ID", "")
SHOW_SENDER = os.getenv("RELAY_SHOW_SENDER", "1") == "1"
TOPIC_MAP_PATH = os.getenv("RELAY_TOPIC_MAP_PATH", "data/relay_topics.json")
GENERAL_TOPIC = 1


def _topic_set(var: str) -> set[str]:
    return {t.strip().lower() for t in os.getenv(var, "").split(",") if t.strip()}


# temas del origen (ids o nombres separados por comas): si ONLY_TOPICS tiene algo, solo se
# copian esos; si no, se copian todos menos los de SKIP_TOPICS
ONLY_TOPICS = _topic_set("RELAY_ONLY_TOPICS")
SKIP_TOPICS = _topic_set("RELAY_SKIP_TOPICS")
# texto que sustituye a la linea "Consejo: ..." del origen (vacio = quitarla; sin definir = dejarla)
TIP_TEXT = os.getenv("RELAY_TIP_TEXT")
TIP_LINE = re.compile(r"^[^\w\n]*Consejo[ \t]*:.*$", re.IGNORECASE | re.MULTILINE)
MAX_FILE_BYTES = 20 * 1024 * 1024  # limite de descarga del Bot API para reenviar ficheros


def rewrite_tip(text: str, replacement: str | None) -> str:
    """Cambia la linea "Consejo: ..." del origen: la sustituye por `replacement`
    (o la quita si esta vacio). Con None deja el texto como esta."""
    if replacement is None:
        return text
    text = TIP_LINE.sub(replacement, text)
    return text.strip() if not replacement else text


def build_text(sender: str | None, text: str | None) -> str:
    text = rewrite_tip((text or "").strip(), TIP_TEXT)
    if sender and SHOW_SENDER:
        return f"{sender}: {text}" if text else f"{sender}:"
    return text


def _pick_source(source: str):
    """Los ids de chat son numericos (-100...); si no, se busca por titulo."""
    try:
        return int(source)
    except ValueError:
        return source


def topic_id_of(message) -> int:
    """Tema del grupo origen al que pertenece el mensaje (1 = General / sin temas)."""
    reply = getattr(message, "reply_to", None)
    if not reply or not getattr(reply, "forum_topic", False):
        return GENERAL_TOPIC
    return reply.reply_to_top_id or reply.reply_to_msg_id or GENERAL_TOPIC


def _load_topic_map() -> dict[str, int]:
    try:
        with open(TOPIC_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_topic_map(mapping: dict[str, int]) -> None:
    os.makedirs(os.path.dirname(TOPIC_MAP_PATH) or ".", exist_ok=True)
    with open(TOPIC_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f)


def _listed(topic_id: int, topic_name: str | None, names: set[str]) -> bool:
    return str(topic_id) in names or (topic_name is not None and topic_name.lower() in names)


def should_relay(topic_id: int, topic_name: str | None, only: set[str], skip: set[str]) -> bool:
    if only:
        return _listed(topic_id, topic_name, only)
    return not _listed(topic_id, topic_name, skip)


def _needs_name(*sets: set[str]) -> bool:
    return any(not item.isdigit() for names in sets for item in names)


async def _topic_name(tg, source_entity, topic_id: int, names: dict[int, str]) -> str:
    if topic_id == GENERAL_TOPIC:
        return "General"
    if topic_id not in names:
        from telethon.tl.functions.messages import GetForumTopicsByIDRequest

        res = await tg(GetForumTopicsByIDRequest(peer=source_entity, topics=[topic_id]))
        names[topic_id] = res.topics[0].title if res.topics else f"Tema {topic_id}"
    return names[topic_id]


async def _target_thread(client: httpx.AsyncClient, tg, source_entity, topic_id: int, topic_map: dict, names: dict) -> tuple[int | None, str | None]:
    """(thread destino, nombre a anteponer si no hay tema donde publicar).
    Crea en el destino el tema equivalente la primera vez que aparece uno."""
    if topic_id == GENERAL_TOPIC:
        return None, None
    key = str(topic_id)
    if key in topic_map:
        return topic_map[key], None
    name = await _topic_name(tg, source_entity, topic_id, names)
    created = await _bot_call(client, "createForumTopic", {"chat_id": TARGET_CHAT, "name": name[:128]})
    if created and created.get("ok"):
        topic_map[key] = created["result"]["message_thread_id"]
        _save_topic_map(topic_map)
        return topic_map[key], None
    log.warning("no se pudo crear el tema '%s' en el destino (activa Temas y da permiso 'Gestionar temas' al bot)", name)
    return None, name


async def _bot_call(client: httpx.AsyncClient, method: str, data: dict, files: dict | None = None) -> dict | None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for _ in range(3):
        resp = await client.post(url, data=data, files=files)
        if resp.status_code == 429:
            await asyncio.sleep(resp.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if resp.status_code != 200:
            log.error("Bot API %s fallo: %s %s", method, resp.status_code, resp.text[:200])
            return None
        return resp.json()
    return None


async def _relay(client: httpx.AsyncClient, message, thread_id: int | None = None, topic_name: str | None = None) -> None:
    sender = None
    if SHOW_SENDER:
        who = await message.get_sender()
        sender = getattr(who, "first_name", None) or getattr(who, "title", None) or "?"
    caption = build_text(sender, message.text)
    if topic_name:  # el destino no tiene ese tema: se indica en el propio mensaje
        caption = f"[{topic_name}] {caption}".strip()
    data = {"chat_id": TARGET_CHAT}
    if thread_id:
        data["message_thread_id"] = thread_id

    if message.photo or message.document:
        size = message.file.size if message.file else 0
        if size and size > MAX_FILE_BYTES:
            await _bot_call(client, "sendMessage", {**data, "text": f"{caption}\n[archivo grande omitido]".strip()})
            return
        buf = io.BytesIO()
        await message.download_media(file=buf)
        buf.seek(0)
        method, field = ("sendPhoto", "photo") if message.photo else ("sendDocument", "document")
        name = (message.file.name if message.file and message.file.name else "archivo")
        await _bot_call(client, method, {**data, "caption": caption[:1024]}, {field: (name, buf)})
        return

    if not caption:
        return
    await _bot_call(client, "sendMessage", {**data, "text": caption[:4096]})


async def run() -> None:
    from telethon import TelegramClient, events

    _require(API_ID and API_HASH, "TG_API_ID y TG_API_HASH")
    _require(SOURCE_CHAT and BOT_TOKEN and TARGET_CHAT, "RELAY_SOURCE_CHAT, RELAY_TARGET_CHAT_ID y el token del bot")
    lock = asyncio.Lock()  # mantiene el orden de los mensajes
    async with httpx.AsyncClient(timeout=60) as http:
        tg = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        await tg.connect()
        if not await tg.is_user_authorized():
            sys.exit("No hay sesion. Ejecuta primero: python -m telegram_source.relay login")

        source_entity = await tg.get_input_entity(_pick_source(SOURCE_CHAT))
        topic_map = _load_topic_map()
        names: dict[int, str] = {}

        @tg.on(events.NewMessage(chats=_pick_source(SOURCE_CHAT)))
        async def handler(event):
            if event.message.action:  # avisos de servicio (alguien entra, cambia el titulo...)
                return
            async with lock:
                try:
                    topic_id = topic_id_of(event.message)
                    name = await _topic_name(tg, source_entity, topic_id, names) if _needs_name(ONLY_TOPICS, SKIP_TOPICS) else None
                    if not should_relay(topic_id, name, ONLY_TOPICS, SKIP_TOPICS):
                        return
                    thread_id, topic_name = await _target_thread(http, tg, source_entity, topic_id, topic_map, names)
                    await _relay(http, event.message, thread_id, topic_name)
                except Exception:
                    log.exception("no se pudo copiar el mensaje %s", event.message.id)

        log.info("Escuchando %s -> %s", SOURCE_CHAT, TARGET_CHAT)
        await tg.run_until_disconnected()


async def login() -> None:
    from telethon import TelegramClient

    _require(API_ID and API_HASH, "TG_API_ID y TG_API_HASH")
    os.makedirs(os.path.dirname(SESSION_PATH) or ".", exist_ok=True)
    tg = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg.start()  # pide telefono y codigo por consola
    me = await tg.get_me()
    print(f"Sesion creada para {me.first_name}. Ya puedes cerrar y usar 'chats' o 'run'.")
    await tg.disconnect()


async def login_qr() -> None:
    """Login por QR: en el movil, Ajustes > Dispositivos > Vincular dispositivo."""
    import getpass

    import qrcode
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    _require(API_ID and API_HASH, "TG_API_ID y TG_API_HASH")
    os.makedirs(os.path.dirname(SESSION_PATH) or ".", exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tg = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg.connect()
    if await tg.is_user_authorized():
        print("Ya hay una sesion valida.")
        await tg.disconnect()
        return
    qr_login = await tg.qr_login()
    for _ in range(5):  # el QR caduca cada ~30 s; se regenera
        code = qrcode.QRCode(border=1)
        code.add_data(qr_login.url)
        code.print_ascii(invert=True)
        print("Escanealo: Telegram > Ajustes > Dispositivos > Vincular dispositivo de escritorio")
        try:
            await qr_login.wait(30)
            break
        except asyncio.TimeoutError:
            await qr_login.recreate()
        except SessionPasswordNeededError:
            await tg.sign_in(password=getpass.getpass("Contrasena de verificacion en dos pasos: "))
            break
    if not await tg.is_user_authorized():
        await tg.disconnect()
        sys.exit("No se completo el login por QR.")
    me = await tg.get_me()
    print(f"Sesion creada para {me.first_name}. Ya puedes usar 'chats' o 'run'.")
    await tg.disconnect()


async def topics() -> None:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetForumTopicsRequest

    tg = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg.connect()
    if not await tg.is_user_authorized():
        sys.exit("No hay sesion. Ejecuta primero: python -m telegram_source.relay login")
    _require(SOURCE_CHAT, "RELAY_SOURCE_CHAT")
    entity = await tg.get_input_entity(_pick_source(SOURCE_CHAT))
    from telethon.errors import RPCError

    try:
        res = await tg(GetForumTopicsRequest(peer=entity, offset_date=None, offset_id=0, offset_topic=0, limit=100))
    except RPCError as e:
        await tg.disconnect()
        sys.exit(f"Telegram responde: {type(e).__name__}: {e}. Si es 'FORUM_MISSING', el grupo origen no tiene Temas activados.")
    for t in res.topics:
        print(f"{t.id}	{t.title}")
    await tg.disconnect()


async def chats() -> None:
    from telethon import TelegramClient

    tg = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg.connect()
    if not await tg.is_user_authorized():
        sys.exit("No hay sesion. Ejecuta primero: python -m telegram_source.relay login")
    async for d in tg.iter_dialogs(limit=50):
        print(f"{d.id}\t{d.name}")
    await tg.disconnect()


def _require(ok, what: str) -> None:
    if not ok:
        sys.exit(f"Falta configurar en .env: {what}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    commands = {"login": login, "qr": login_qr, "chats": chats, "topics": topics, "run": run}
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in commands:
        sys.exit(__doc__)
    asyncio.run(commands[cmd]())


if __name__ == "__main__":
    main()
