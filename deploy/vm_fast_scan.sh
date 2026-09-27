#!/usr/bin/env bash
# Ciclo RAPIDO en la VM: equivalente a scripts/local_scan.ps1 pero para systemd
# (ver deploy/surebets-fast.service/.timer). Corre scan_once_action.py --mode
# fast (fuentes directas + cache de comparadores) y empuja docs/data.json +
# data/ a GitHub, igual que hacia el Programador de tareas de Windows - asi
# sigue actualizandose el panel de GitHub Pages sin depender del PC del
# usuario. Los logs van al journal de systemd (journalctl -u surebets-fast),
# no a un fichero: no hace falta la redireccion manual que usa la version de
# PowerShell.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PYTHONPATH="$APP_DIR"
PYTHON="$APP_DIR/.venv/bin/python"

"$PYTHON" scripts/scan_once_action.py --mode fast
scan_exit=$?

if [ "$scan_exit" -ne 0 ]; then
  echo "El escaneo fallo con codigo $scan_exit" >&2
  exit "$scan_exit"
fi

git add data/ docs/data.json
if git diff --cached --quiet; then
  echo "Sin cambios que commitear"
  exit 0
fi

git commit -q -m "chore: actualizar estado del escaneo (VM)"

if git push -q; then
  echo "Cambios commiteados y pusheados"
  exit 0
fi

echo "git push rechazado, intentando 'git pull' para sincronizar con el remoto" >&2
if git pull -q --no-edit; then
  if git push -q; then
    echo "Cambios commiteados y pusheados tras sincronizar"
    exit 0
  fi
fi

echo "No se pudo sincronizar con GitHub (conflicto real) - revisar manualmente" >&2
exit 1
