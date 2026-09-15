#!/usr/bin/env bash
# Ejecutar en la VM (Ubuntu) una vez copiado el código a ~/surebets.
# Instala dependencias del sistema, crea el venv, instala Playwright y
# registra el bot como servicio systemd para que arranque solo y se
# reinicie si falla o si la VM se reinicia.
set -euo pipefail

APP_DIR="$HOME/surebets"
SERVICE_NAME="surebets"

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

echo "== Instalando servicio systemd =="
sed \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__USER__#$(whoami)#g" \
  "$APP_DIR/deploy/surebets.service" | sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo "== Listo. Para arrancar el bot: =="
echo "  sudo systemctl start $SERVICE_NAME"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f   # logs en vivo"
