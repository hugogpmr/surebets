#!/usr/bin/env bash
# Sube a GitHub el panel (docs/data.json) y el estado de avisos (data/) que va escribiendo el modo
# continuo (deploy/surebets-live.service). Antes lo hacía vm_fast_scan.sh al final de cada ciclo;
# el modo continuo analiza cada minuto y no tiene sentido un commit por análisis. Lo lanza
# deploy/surebets-publish.timer.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

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
if git pull -q --no-edit && git push -q; then
  echo "Cambios commiteados y pusheados tras sincronizar"
  exit 0
fi

echo "No se pudo sincronizar con GitHub (conflicto real) - revisar manualmente" >&2
exit 1
