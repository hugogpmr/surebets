#!/usr/bin/env bash
# Ciclo LENTO en la VM: equivalente a scripts/local_slow_scan.ps1. Solo
# refresca cache/ (comparadores) para que el ciclo rapido la lea - no toca
# git ni Telegram. Logs en journalctl -u surebets-slow.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PYTHONPATH="$APP_DIR"
"$APP_DIR/.venv/bin/python" scripts/scan_once_action.py --mode slow
