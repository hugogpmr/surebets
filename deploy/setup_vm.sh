#!/usr/bin/env bash
# Ejecutar en la VM (Ubuntu) una vez copiado el código a ~/surebets.
# Instala dependencias del sistema, crea el venv, instala Playwright y
# registra el bot (y el relay, si su sesión ya está copiada) como servicios
# systemd para que arranquen solos y se reinicien si fallan o si la VM se
# reinicia.
set -euo pipefail

APP_DIR="$HOME/surebets"
SERVICE_NAME="surebets"
RELAY_SERVICE_NAME="surebets-relay"

if [ ! -d "$APP_DIR" ]; then
  echo "No existe $APP_DIR. Copia primero el proyecto ahí (ver deploy/README_DEPLOY.md)." >&2
  exit 1
fi

echo "== Instalando dependencias del sistema =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

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

echo "== Instalando servicio systemd (bot) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets.service" | sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null

echo "== Instalando servicio systemd (relay) =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets-relay.service" | sudo tee /etc/systemd/system/${RELAY_SERVICE_NAME}.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" "$RELAY_SERVICE_NAME"

if [ ! -f "$APP_DIR/data/relay.session" ]; then
  echo "AVISO: no hay $APP_DIR/data/relay.session. El relay (systemd $RELAY_SERVICE_NAME) no podrá" >&2
  echo "arrancar hasta que copies esa sesión (créala en tu PC con 'python -m telegram_source.relay login'" >&2
  echo "o 'qr', y haz scp de data/relay.session* a la VM) o hagas el login directamente por SSH." >&2
fi

echo "== Listo. Para arrancar el bot y el relay: =="
echo "  sudo systemctl start $SERVICE_NAME $RELAY_SERVICE_NAME"
echo "  sudo systemctl status $SERVICE_NAME $RELAY_SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f          # logs en vivo del bot"
echo "  journalctl -u $RELAY_SERVICE_NAME -f    # logs en vivo del relay"
