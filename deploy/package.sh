#!/usr/bin/env bash
# Empaqueta el proyecto (sin .venv, .env, la base de datos ni cachés) en
# surebets.tar.gz, listo para copiar a la VM con scp.
set -euo pipefail
cd "$(dirname "$0")/.."

tar -czf surebets.tar.gz \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='surebets.db' \
  --exclude='__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='surebets.tar.gz' \
  .

echo "Creado: $(pwd)/surebets.tar.gz"
