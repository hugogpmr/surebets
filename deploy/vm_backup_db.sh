#!/usr/bin/env bash
# Copia nocturna de las bases de datos de la VM (ver deploy/surebets-backup.service/.timer).
# data/surebets.db ya no está en git (2026-10-01) y solo vive en la VM: esto deja una copia
# coherente y comprimida en BACKUP_DIR, que la Raspberry de casa descarga a su disco externo
# (deploy/raspberry/README.md, "Copia de seguridad"). Se copia con la API de backup de SQLite,
# no con cp: un cp a mitad de un escaneo que está escribiendo puede dejar una copia corrupta.
#
# Además vigila el otro lado: la Raspberry deja BACKUP_DIR/.pi_last_ok tras cada descarga
# buena; si lleva más de MAX_PI_AGE_HOURS sin actualizarse se avisa al canal de administración
# (así la Raspberry no necesita el token del bot).
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
export PYTHONPATH="$APP_DIR"
PYTHON="$APP_DIR/.venv/bin/python"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/surebets}"
MAX_PI_AGE_HOURS="${MAX_PI_AGE_HOURS:-30}"

alert() { "$PYTHON" scripts/alert_admin.py "$1" || true; }

if ! "$PYTHON" - "$BACKUP_DIR" <<'EOF'
import gzip, os, shutil, sqlite3, sys, tempfile
dest = sys.argv[1]
for src, name in (("data/surebets.db", "surebets.db.gz"), ("cache/backtest.db", "backtest.db.gz")):
    if not os.path.exists(src):
        print(f"{src}: no existe, se salta")
        continue
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap.db")
        with sqlite3.connect(src) as s, sqlite3.connect(snap) as d:
            s.backup(d)
        with sqlite3.connect(snap) as d:
            check = d.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise SystemExit(f"{src}: quick_check de la copia = {check}")
        part = os.path.join(dest, name + ".part")
        with open(snap, "rb") as f, gzip.open(part, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
        os.chmod(part, 0o640)
        os.replace(part, os.path.join(dest, name))
        print(f"{src} -> {name}: {os.path.getsize(os.path.join(dest, name)) / 1e6:.1f} MB")
EOF
then
  echo "La copia de las bases de datos falló" >&2
  alert "🔴 La copia nocturna de la base de datos en la VM falló. Mira: journalctl -u surebets-backup"
  exit 1
fi

marker="$BACKUP_DIR/.pi_last_ok"
if [ ! -f "$marker" ]; then
  alert "🟠 La Raspberry todavía no ha descargado ninguna copia de la base de datos."
elif [ $(( ($(date +%s) - $(stat -c %Y "$marker")) / 3600 )) -ge "$MAX_PI_AGE_HOURS" ]; then
  alert "🟠 La Raspberry lleva más de ${MAX_PI_AGE_HOURS} h sin descargar la copia de la base de datos (¿apagada, sin disco o sin red?)."
fi
