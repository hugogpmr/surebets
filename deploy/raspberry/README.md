# Raspberry Pi: salida por la conexión de casa

Algunas casas bloquean la IP de datacenter de la VM pero no una IP residencial
(William Hill: 403 desde la VM, 200 por la Raspberry; bwin: "Failed to fetch"
desde la VM, ~10k mercados por la Raspberry, medido 2026-10-02). La Raspberry
de casa abre un túnel SSH inverso hacia la VM y hace de proxy SOCKS: en la VM
queda `socks5://127.0.0.1:1080`, que sale a internet por la conexión de casa.
La Raspberry no lee nada, solo reenvía tráfico. No hay que abrir puertos en el
router: la conexión la inicia la Raspberry.

Las fuentes lo usan solo si se les pasa `config.RESIDENTIAL_PROXY`
(`RESIDENTIAL_PROXY=socks5://127.0.0.1:1080` en el `.env` de la VM). Si la
Raspberry está apagada, esas fuentes fallan como antes y el resto del escaneo
sigue igual.

## Montaje (hecho el 2026-10-02)

Raspberry Pi 4 (2 GB), Raspberry Pi OS Lite 64-bit, nombre `surebets-pi`,
usuario `pi`, por cable.

1. En la Raspberry, llave para el túnel:
   `ssh-keygen -t ed25519 -N "" -C pi-tunnel@surebets-pi -f ~/.ssh/vm_tunnel`
2. En la VM, usuario que solo puede abrir ese túnel:
   ```sh
   useradd --system --create-home --shell /usr/sbin/nologin pitunnel
   install -d -m 700 -o pitunnel -g pitunnel /home/pitunnel/.ssh
   echo 'restrict,port-forwarding,permitlisten="127.0.0.1:1080",command="/usr/sbin/nologin" <contenido de vm_tunnel.pub>' \
     > /home/pitunnel/.ssh/authorized_keys
   chown pitunnel:pitunnel /home/pitunnel/.ssh/authorized_keys; chmod 600 /home/pitunnel/.ssh/authorized_keys
   ```
3. En la Raspberry, servicio de usuario (el usuario `pi` no tiene sudo sin
   contraseña; con `linger` arranca igual al encender, sin sesión abierta):
   ```sh
   ssh-keyscan -t ed25519 194.62.96.198 >> ~/.ssh/known_hosts
   loginctl enable-linger pi
   mkdir -p ~/.config/systemd/user
   cp surebets-tunnel.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now surebets-tunnel.service
   ```
4. Comprobar desde la VM:
   `curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me` debe dar la IP de casa.

## Vigilante de la VM (montado el 2026-10-02)

Los avisos de la VM (`scripts/alert_admin.py`) no llegan si la VM entera se
cae: nadie queda vivo para mandarlos. `surebets-watchdog.py` mira desde casa
cada 5 min y avisa al mismo canal de administración:

- el panel publicado en GitHub (`docs/data.json`) tiene más de 30 min;
- la caché del comparador (ciclo lento) tiene más de 60 min;
- el puerto SSH de la VM no responde;
- el servicio `surebets-tunnel` no está activo;
- el disco de los backups no está montado en `/mnt/backup`;
- la copia en Google Drive lleva más de 30 h sin subirse.

Avisa tras 2 fallos seguidos, lo recuerda cada 6 h y avisa al recuperarse.
Solo usa la biblioteca estándar de Python. Token y canal en
`~/.config/surebets-watchdog/env` (permisos 600, copiados de `.env` de la VM:
`TELEGRAM_BOT_TOKEN` y `ADMIN_ALERT_CHAT_ID`); estado en `state.json` al lado.

```sh
cp surebets-watchdog.py ~/ && chmod 755 ~/surebets-watchdog.py
cp surebets-watchdog.service surebets-watchdog.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now surebets-watchdog.timer
python3 ~/surebets-watchdog.py --dry-run   # ver el estado sin avisar
```

## Copia en Google Drive (montada el 2026-10-02)

Tras guardar la copia en el disco externo, `surebets-backup-pull.sh` la sube
también a `gdrive:surebets-backups/{daily,weekly}` con la misma retención (30
días y 26 semanas, ~400 MB). Si la subida falla, la copia local sigue hecha y
el vigilante avisa cuando pasan 30 h sin subir.

- rclone instalado sin sudo en `~/bin/rclone` (binario oficial de
  downloads.rclone.org, comprobado con su SHA256SUMS).
- Remoto `gdrive` con `scope=drive.file`: solo ve lo que sube él, no el resto
  del Drive. Autorizado con un túnel al puerto de rclone desde el PC, que tiene
  navegador:
  ```sh
  ssh -L 53682:127.0.0.1:53682 pi@192.168.1.17 '~/bin/rclone config create gdrive drive scope=drive.file'
  ```
  y abrir en el navegador del PC el enlace `http://127.0.0.1:53682/auth?...` que imprime.
- Usa el client_id compartido de rclone, que Google va a retirar durante 2026.
  Si las subidas empiezan a fallar, crear un client_id propio
  (https://rclone.org/drive/#making-your-own-client-id) y repetir el paso de arriba
  con `client_id=... client_secret=...`.
- Restaurar: `~/bin/rclone copy gdrive:surebets-backups/daily/AAAA-MM-DD ./restaurar`
  y `gunzip` de los `.db.gz`.
