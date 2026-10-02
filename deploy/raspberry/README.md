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
