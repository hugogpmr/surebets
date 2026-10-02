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

# Segunda copia fuera de casa (Google Drive, remoto "gdrive" de rclone con scope drive.file: solo
# ve lo que sube él). Si falla no tumba la copia local, que ya está hecha: el vigilante
# (surebets-watchdog.py) avisa si DRIVE_MARKER envejece.
RCLONE="$HOME/bin/rclone"
DRIVE="gdrive:surebets-backups"
DRIVE_MARKER="$HOME/.config/surebets-watchdog/drive_last_ok"
if [ -x "$RCLONE" ] && "$RCLONE" listremotes | grep -qx 'gdrive:'; then
  if "$RCLONE" copy "$DEST/daily/$day" "$DRIVE/daily/$day" \
     && { [ "$(date -u +%u)" != 7 ] || "$RCLONE" copy "$DEST/weekly/$day" "$DRIVE/weekly/$day"; }; then
    # Misma retención que en el disco (la edad cuenta desde el cp de arriba, es decir, el día de la copia).
    "$RCLONE" delete "$DRIVE/daily" --min-age "$((KEEP_DAILY + 1))d" --rmdirs || true
    "$RCLONE" delete "$DRIVE/weekly" --min-age "$((KEEP_WEEKLY * 7 + 1))d" --rmdirs || true
    date -u +%FT%TZ > "$DRIVE_MARKER"
    echo "Copia subida a Google Drive ($DRIVE/daily/$day)"
  else
    echo "No se pudo subir la copia a Google Drive" >&2
  fi
fi
