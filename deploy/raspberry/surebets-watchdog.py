#!/usr/bin/env python3
"""Vigilante de la VM de surebets que corre en la Raspberry de casa (surebets-watchdog.timer).

Los avisos de la propia VM (scripts/alert_admin.py) no sirven si la VM entera se cae o se queda
colgada: nadie queda vivo para avisar. Este script mira desde fuera, cada pocos minutos, y manda
el aviso al mismo canal de administración por la API de Telegram (sin python-telegram-bot: solo
biblioteca estándar, la Raspberry no tiene el entorno del proyecto).

Comprobaciones:
  panel        docs/data.json publicado en GitHub con generated_at reciente: cubre VM caída,
               escaneo parado y git push roto, todo a la vez.
  comparador   la caché de casasdeapuestas (ciclo lento) se sigue refrescando.
  vm_ssh       el puerto SSH de la VM responde.
  tunel        el servicio surebets-tunnel de la Raspberry está activo.
  disco        el disco externo de los backups está montado.
  drive        la copia nocturna se sigue subiendo a Google Drive.

Solo avisa cuando una comprobación falla FAILS_TO_ALERT veces seguidas (evita avisos por un
corte de un minuto), recuerda cada REMIND_HOURS si sigue igual y avisa al recuperarse. El estado
se guarda en STATE_FILE. Token y canal salen de ENV_FILE (TELEGRAM_BOT_TOKEN, ADMIN_ALERT_CHAT_ID).

    surebets-watchdog.py           # una pasada (lo que hace el timer)
    surebets-watchdog.py --dry-run # imprime el resultado sin avisar ni guardar estado
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PANEL_URL = "https://raw.githubusercontent.com/hugogpmr/surebets/main/docs/data.json"
VM_HOST = "194.62.96.198"
BACKUP_MOUNT = "/mnt/backup"
# El ciclo rápido publica cada ~7 min; raw.githubusercontent.com cachea hasta 5 min más.
MAX_PANEL_AGE_MIN = 30
# El ciclo lento tarda ~18 min y vuelve a empezar 2 min después; la caché más nueva no debería
# pasar de ~25 min.
MAX_COMPARATOR_AGE_MIN = 60
FAILS_TO_ALERT = 2
REMIND_HOURS = 6

CONFIG_DIR = Path.home() / ".config" / "surebets-watchdog"
ENV_FILE = CONFIG_DIR / "env"
STATE_FILE = CONFIG_DIR / "state.json"
DRIVE_MARKER = CONFIG_DIR / "drive_last_ok"
# La copia se sube una vez al día (04:00 UTC); igual margen que la VM con .pi_last_ok.
MAX_DRIVE_AGE_HOURS = 30


def check_panel() -> tuple[bool, str, dict | None]:
    try:
        req = urllib.request.Request(PANEL_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as exc:
        return False, f"no se pudo leer el panel de GitHub ({exc.__class__.__name__})", None
    generated = datetime.fromisoformat(data["generated_at"])
    age = (datetime.now(timezone.utc) - generated).total_seconds() / 60
    if age > MAX_PANEL_AGE_MIN:
        return False, f"el panel lleva {age:.0f} min sin actualizarse (escaneo o publicación parados)", data
    return True, f"panel actualizado hace {age:.0f} min", data


def check_comparator(data: dict | None) -> tuple[bool, str]:
    if data is None:
        return True, "sin panel, no se comprueba"
    cache = data.get("settings", {}).get("sources", {}).get("casasdeapuestas", {}).get("cache")
    if not cache:
        return False, "el panel no trae la caché del comparador (¿ciclo lento sin datos?)"
    newest = cache.get("newest_minutes", 0)
    if newest > MAX_COMPARATOR_AGE_MIN:
        return False, f"la caché del comparador lleva {newest} min sin refrescarse (ciclo lento parado)"
    return True, f"comparador refrescado hace {newest} min"


def check_vm_ssh() -> tuple[bool, str]:
    try:
        with socket.create_connection((VM_HOST, 22), timeout=15) as sock:
            banner = sock.recv(64)
    except OSError as exc:
        return False, f"la VM no responde por SSH ({exc.__class__.__name__})"
    if not banner.startswith(b"SSH-"):
        return False, "la VM responde por el puerto 22 pero no como SSH"
    return True, "VM responde por SSH"


def check_tunnel() -> tuple[bool, str]:
    state = subprocess.run(["systemctl", "--user", "is-active", "surebets-tunnel.service"],
                           capture_output=True, text=True).stdout.strip()
    if state != "active":
        return False, f"el túnel de la Raspberry hacia la VM no está activo ({state})"
    return True, "túnel activo"


def check_disk() -> tuple[bool, str]:
    if not os.path.ismount(BACKUP_MOUNT):
        return False, f"el disco de los backups no está montado en {BACKUP_MOUNT}"
    return True, "disco de backups montado"


def check_drive() -> tuple[bool, str]:
    # surebets-backup-pull.sh lo deja tras subir la copia a Google Drive. Sin fichero = aún no
    # se ha subido nunca (recién montado): no se avisa.
    if not DRIVE_MARKER.exists():
        return True, "copia en Google Drive aún sin estrenar"
    age = (time.time() - DRIVE_MARKER.stat().st_mtime) / 3600
    if age > MAX_DRIVE_AGE_HOURS:
        return False, f"la copia en Google Drive lleva {age:.0f} h sin subirse"
    return True, f"copia en Google Drive subida hace {age:.0f} h"


def run_checks() -> dict[str, tuple[bool, str]]:
    panel_ok, panel_msg, data = check_panel()
    return {
        "panel": (panel_ok, panel_msg),
        "comparador": check_comparator(data),
        "vm_ssh": check_vm_ssh(),
        "tunel": check_tunnel(),
        "disco": check_disk(),
        "drive": check_drive(),
    }


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def send(env: dict[str, str], text: str) -> bool:
    url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": env["ADMIN_ALERT_CHAT_ID"], "text": text}).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=30) as resp:
            return resp.status == 200
    except Exception as exc:
        # Sin la URL: lleva el token dentro.
        print(f"No se pudo mandar el aviso: {exc.__class__.__name__}", file=sys.stderr)
        return False


def main() -> int:
    results = run_checks()
    for name, (ok, msg) in results.items():
        print(f"{'OK ' if ok else 'MAL'} {name}: {msg}")
    if "--dry-run" in sys.argv:
        return 0

    env = load_env()
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        state = {}
    now = time.time()

    for name, (ok, msg) in results.items():
        st = state.setdefault(name, {"fails": 0, "alerted_at": None})
        if ok:
            # Solo se anuncia la recuperación de lo que se llegó a avisar.
            if st["alerted_at"] is not None and send(env, f"🟢 Raspberry: recuperado — {msg}."):
                st["alerted_at"] = None
            if st["alerted_at"] is None:
                st["fails"] = 0
            continue
        st["fails"] += 1
        if st["fails"] < FAILS_TO_ALERT:
            continue
        if st["alerted_at"] is None:
            if send(env, f"🔴 Raspberry: {msg}."):
                st["alerted_at"] = now
        elif now - st["alerted_at"] >= REMIND_HOURS * 3600:
            if send(env, f"🟠 Raspberry: sigue fallando — {msg}."):
                st["alerted_at"] = now

    STATE_FILE.write_text(json.dumps(state, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
