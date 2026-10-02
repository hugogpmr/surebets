#!/usr/bin/env bash
# Descarga la copia nocturna de las bases de datos de la VM (deploy/vm_backup_db.sh) al disco
# externo de la Raspberry y guarda historial: una carpeta por día (KEEP_DAILY días) y otra por
# domingo (KEEP_WEEKLY semanas). Tras una descarga buena deja .pi_last_ok en la VM: si deja de
# llegar, la propia VM avisa por Telegram (aquí no hay token del bot).
set -euo pipefail

VM="pibackup@194.62.96.198"
KEY="$HOME/.ssh/vm_backup"
MOUNT="/mnt/backup"
DEST="$MOUNT/surebets-backups"
KEEP_DAILY=30
KEEP_WEEKLY=26
SSH="ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=yes"

mountpoint -q "$MOUNT" || { echo "El disco externo no está montado en $MOUNT" >&2; exit 1; }

mkdir -p "$DEST/latest" "$DEST/daily" "$DEST/weekly"
rsync -rt --timeout=300 --include='*.db.gz' --exclude='*' -e "$SSH" "$VM:./" "$DEST/latest/"

day="$(date -u +%F)"
rm -rf "$DEST/daily/$day"
cp -r "$DEST/latest" "$DEST/daily/$day"
if [ "$(date -u +%u)" = 7 ]; then
  rm -rf "$DEST/weekly/$day"
  cp -r "$DEST/latest" "$DEST/weekly/$day"
fi

# Las carpetas se llaman AAAA-MM-DD: orden alfabético = orden de fecha.
ls -1 "$DEST/daily" | head -n -"$KEEP_DAILY" | while read -r old; do rm -rf "$DEST/daily/$old"; done
ls -1 "$DEST/weekly" | head -n -"$KEEP_WEEKLY" | while read -r old; do rm -rf "$DEST/weekly/$old"; done

marker="$(mktemp)"
date -u +%FT%TZ > "$marker"
rsync --timeout=60 -e "$SSH" "$marker" "$VM:./.pi_last_ok"
rm -f "$marker"
echo "Copia guardada en $DEST/daily/$day: $(du -sh "$DEST/daily/$day" | cut -f1)"
