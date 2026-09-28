#!/usr/bin/env bash
# Ejecutar en la VM (Ubuntu) una vez copiado el código a ~/surebets.
# Instala dependencias del sistema, crea el venv, instala Playwright y
# registra el bot de dos velocidades (bot solo-lectura + timers fast/slow,
# ver más abajo) y el relay (si su sesión ya está copiada) como servicios
# systemd para que arranquen solos y se reinicien si fallan o si la VM se
# reinicia. Es idempotente: se puede volver a ejecutar tras un `git pull`
# para actualizar dependencias/unidades sin duplicar nada.
set -euo pipefail

APP_DIR="$HOME/surebets"
# Modelo de dos velocidades (ver deploy/README_DEPLOY.md "Migración pendiente..."):
# sustituye al antiguo proceso único `surebets.service` (main.py) - un bot de solo
# lectura (/hoy /ahora /stats) más dos timers (`--mode fast` cada 12 min, `--mode
# slow` cada 30 min), igual que scripts/local_scan.ps1 + local_slow_scan.ps1 en
# Windows.
BOT_SERVICE_NAME="surebets-bot"
FAST_SERVICE_NAME="surebets-fast"
SLOW_SERVICE_NAME="surebets-slow"
RELAY_SERVICE_NAME="surebets-relay"
# Nombre del proceso único antiguo, que este script ya no registra pero sí para y
# deshabilita si lo encuentra activo de una instalación previa (ver más abajo) -
# los dos modelos escaneando a la vez duplicarían cada ciclo.
OLD_SERVICE_NAME="surebets"

if [ ! -d "$APP_DIR" ]; then
  echo "No existe $APP_DIR. Copia primero el proyecto ahí (ver deploy/README_DEPLOY.md)." >&2
  exit 1
fi

echo "== Instalando dependencias del sistema =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

# Swap de 2 GB si no existe ya: añadido a mano el 2026-09-28 tras 10 ciclos rápidos matados
# por el OOM killer del kernel en 24h en una VM de 2 vCPU/3,8 GB sin swap (varios proveedores
# lanzan Chromium con varias pestañas a la vez, ver providers/sportium.py y
# providers/pokerstars.py). Sin esto, un pico de memoria mata el ciclo entero en vez de solo
# ir más lento. Idempotente: si ya hay swap activo (de esta VM o de otra con más RAM que no lo
# necesita) no hace nada.
if ! sudo swapon --show | grep -q .; then
  echo "== Creando swapfile de 2 GB (no había ninguno) =="
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "== Creando entorno virtual =="
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== Instalando Chromium de Playwright y sus dependencias del sistema =="
.venv/bin/playwright install --with-deps chromium

if [ ! -f "$APP_DIR/.env" ]; then
  echo "AVISO: no hay .env en $APP_DIR. Cópialo (scp) antes de arrancar el servicio." >&2
fi

if systemctl is-enabled --quiet "$OLD_SERVICE_NAME" 2>/dev/null || systemctl is-active --quiet "$OLD_SERVICE_NAME" 2>/dev/null; then
  echo "== Migrando desde el modelo de proceso único ($OLD_SERVICE_NAME) =="
  echo "Parando y deshabilitando $OLD_SERVICE_NAME (sustituido por $BOT_SERVICE_NAME + los timers fast/slow)."
  sudo systemctl disable --now "$OLD_SERVICE_NAME"
fi

echo "== Instalando servicio systemd (bot, solo /hoy /ahora /stats) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets-bot.service" | sudo tee /etc/systemd/system/${BOT_SERVICE_NAME}.service > /dev/null

echo "== Instalando servicio + timer systemd (ciclo rápido, cada 12 min) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets-fast.service" | sudo tee /etc/systemd/system/${FAST_SERVICE_NAME}.service > /dev/null
sudo cp "$APP_DIR/deploy/surebets-fast.timer" /etc/systemd/system/${FAST_SERVICE_NAME}.timer

echo "== Instalando servicio + timer systemd (ciclo lento, cada 30 min) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets-slow.service" | sudo tee /etc/systemd/system/${SLOW_SERVICE_NAME}.service > /dev/null
sudo cp "$APP_DIR/deploy/surebets-slow.timer" /etc/systemd/system/${SLOW_SERVICE_NAME}.timer

echo "== Instalando servicio systemd (relay) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets-relay.service" | sudo tee /etc/systemd/system/${RELAY_SERVICE_NAME}.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$BOT_SERVICE_NAME" "${FAST_SERVICE_NAME}.timer" "${SLOW_SERVICE_NAME}.timer" "$RELAY_SERVICE_NAME"

# vm_fast_scan.sh hace "git commit"+"git push" tras cada ciclo (igual que
# local_scan.ps1): sin identidad de git configurada para $(whoami), esos commits
# fallarían en el primer ciclo rápido. No se sobreescribe si ya existe (p.ej. en
# una reinstalación).
if [ -z "$(git config --global user.email || true)" ]; then
  echo "AVISO: no hay identidad de git configurada (git config --global user.name/user.email)." >&2
  echo "vm_fast_scan.sh no podrá commitear data/+docs/data.json hasta que la configures." >&2
fi

if [ ! -f "$APP_DIR/data/relay.session" ]; then
  echo "AVISO: no hay $APP_DIR/data/relay.session. El relay (systemd $RELAY_SERVICE_NAME) no podrá" >&2
  echo "arrancar hasta que copies esa sesión (créala en tu PC con 'python -m telegram_source.relay login'" >&2
  echo "o 'qr', y haz scp de data/relay.session* a la VM) o hagas el login directamente por SSH." >&2
fi

echo "== Listo. Para arrancar el bot, los timers y el relay: =="
echo "  sudo systemctl start $BOT_SERVICE_NAME ${FAST_SERVICE_NAME}.timer ${SLOW_SERVICE_NAME}.timer $RELAY_SERVICE_NAME"
echo "  sudo systemctl status $BOT_SERVICE_NAME ${FAST_SERVICE_NAME}.timer ${SLOW_SERVICE_NAME}.timer $RELAY_SERVICE_NAME"
echo "  journalctl -u $BOT_SERVICE_NAME -f      # logs en vivo del bot (/hoy /ahora /stats)"
echo "  journalctl -u $FAST_SERVICE_NAME -f     # logs del último ciclo rápido"
echo "  journalctl -u $SLOW_SERVICE_NAME -f     # logs del último ciclo lento"
echo "  journalctl -u $RELAY_SERVICE_NAME -f    # logs en vivo del relay"
echo "  systemctl list-timers                   # próxima ejecución de cada timer"
