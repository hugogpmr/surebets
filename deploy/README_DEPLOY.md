# Despliegue 24/7 (sin depender de tu PC)

Dos caminos, según prioridad:

- **Opción A — GitHub Actions: 100% gratis, sin tarjeta, sin crear cuenta en ningún cloud.** Recomendada
  ahora mismo. Limitación real: el bot pasa a ser "solo avisos" — sigues recibiendo la notificación
  automática de cada surebet nueva en Telegram, pero los comandos `/hoy`, `/ahora`, `/stats` dejan de
  responder (necesitan un proceso escuchando todo el rato, que aquí no existe). Por el mismo motivo,
  la fuente de tips de Telegram (`telegram_source/`, ver README) tampoco funciona aquí: necesita una
  conexión de escucha en vivo, no un ciclo suelto cada 15 min. Ver sección A.
- **Opción B — VM propia (Hetzner de pago, u Oracle Always Free si consigues capacidad).** El bot sigue
  siendo el mismo proceso de siempre (con `/hoy`, `/ahora`, `/stats` funcionando) corriendo 24/7 vía
  systemd. Ver sección B.

Se puede hacer primero A (ya, gratis, en minutos) y más adelante montar B si echas de menos los comandos
interactivos — no son excluyentes, es solo qué partes del sistema corren dónde.

---

## Opción A: GitHub Actions (gratis, sin tarjeta)

Cómo funciona: un workflow programado se despierta cada 15 minutos, levanta un runner de Ubuntu
temporal, hace un scan de las 3 casas, y si hay una surebet nueva te manda el aviso a Telegram — todo
sin dejar nada corriendo entre medias. El estado (para no repetir avisos) se guarda en un JSON que el
propio workflow commitea de vuelta al repo. Ya está todo programado en
`.github/workflows/scan.yml` y `scripts/scan_once_action.py`.

Importante: el repo debe ser **público** para que los minutos de Actions sean gratis e ilimitados (en
repos privados el plan gratuito de GitHub solo da 2.000 minutos/mes, que no llegan para escanear cada 15
min). No hay ningún dato sensible en el código — el token de Telegram va como *secret* de GitHub, nunca
en el repo.

### Lo que tienes que hacer tú (cosas con tu propia cuenta/credenciales, no puedo hacerlas por ti)

1. **Rota el token del bot de Telegram** si no lo has hecho ya: [@BotFather](https://t.me/BotFather) →
   `/mybots` → tu bot → Bot Settings → API Token → Revoke, genera uno nuevo y guárdalo.
2. Crea una cuenta en https://github.com (si no tienes) — gratis, sin tarjeta.
3. Crea un repositorio nuevo, **público**, vacío (sin README ni .gitignore, ya los tenemos), por ejemplo
   `surebets`. Cópiame la URL (`https://github.com/tu-usuario/surebets.git`) para que pueda hacer el
   `git push` desde tu propio PC con tu sesión de git ya autenticada.
4. En el repo: **Settings → Secrets and variables → Actions → New repository secret**, y añade dos:
   - `TELEGRAM_BOT_TOKEN` → el token nuevo del paso 1.
   - `TELEGRAM_CHAT_ID` → tu chat id (`2094318125`).
   (Esto lo tienes que pegar tú mismo — un token no debo introducirlo yo en ningún formulario.)
5. Opcional: en **Settings → Secrets and variables → Actions → Variables**, añade `BANKROLL` y
   `MIN_MARGIN` si quieres otros valores que los por defecto (250€ y 1%).
6. Avísame cuando estén los secrets puestos y te hago el `git init` + push del código, y disparo el
   workflow manualmente (botón "Run workflow" en la pestaña Actions, o te digo cómo) para comprobar que
   todo funciona antes de dejarlo en automático.

### Verificar que funciona

- Pestaña **Actions** del repo → debería aparecer una ejecución de "Escaneo de surebets" cada ~15 min.
- Si hay una surebet real, te llega el aviso a Telegram igual que antes.
- Si algo falla, el log del job en esa misma pestaña dice el error exacto.

### El `schedule` de GitHub Actions no es fiable a 5 minutos (comprobado 2026-09-16)

`schedule: cron: "*/5 * * * *"` está puesto en `.github/workflows/scan.yml`, pero GitHub **no garantiza**
ese intervalo: en periodos de carga alta retrasa o directamente descarta ejecuciones programadas, sobre
todo con intervalos cortos como cada 5 min. Comprobado con la API real de Actions del repo: hubo huecos de
~5 horas entre ejecuciones programadas en vez de 5 minutos.

**Solución: disparar el workflow desde un cron externo** (llamando a la API de `workflow_dispatch`, que sí
se ejecuta al instante) en vez de depender solo del `schedule` interno. El `schedule` se deja puesto como
red de respaldo — no molesta, el `concurrency` del workflow evita que se pisen dos ejecuciones a la vez.

**Lo que tienes que hacer tú (credenciales tuyas, no debo tocarlas yo):**

1. Crea un **fine-grained personal access token**: github.com → foto de perfil → **Settings → Developer
   settings → Personal access tokens → Fine-grained tokens → Generate new token**.
   - **Repository access**: "Only select repositories" → `surebets` (nunca "All repositories").
   - **Permissions → Repository permissions → Actions**: `Read and write`. No hace falta ningún otro permiso.
   - Expiración: la que prefieras (se puede rotar cuando quieras desde la misma pantalla).
   - Copia el token (`github_pat_...`) — solo se muestra una vez.
2. Crea una cuenta gratis en https://cron-job.org (o el servicio de cron externo que prefieras).
3. **Create cronjob**:
   - **URL**: `https://api.github.com/repos/hugogpmr/surebets/actions/workflows/scan.yml/dispatches`
   - **Request method**: `POST`
   - **Headers**:
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer TU_TOKEN_AQUI`
     - `Content-Type: application/json`
     - `User-Agent: cron-job.org` (la API de GitHub exige un User-Agent, si no la request falla)
   - **Body**: `{"ref":"main"}`
   - **Schedule**: cada 5 minutos.
   - (El token lo pegas tú directamente en el formulario de cron-job.org — es tu credencial, no debo
     introducirla yo en ningún sitio.)
4. Guarda el cronjob y pulsa "Run now" una vez para probarlo: una respuesta `204 No Content` significa que
   disparó bien. Confírmalo también en la pestaña **Actions** del repo — debería aparecer un run nuevo con
   evento `workflow_dispatch`.

**Seguridad del token**: solo tiene permiso de escritura en Actions de este repo (nada de código, nada de
otros repos). Si alguna vez quieres revocarlo: misma pantalla de **Fine-grained tokens** → Delete.

---

## Opción B: VM propia (Hetzner de pago, o reintentar Oracle Always Free)

Aquí sí corre el bot "de verdad", igual que en tu PC ahora mismo, con `/hoy`/`/ahora`/`/stats`
funcionando. `deploy/setup_vm.sh` y `deploy/surebets.service` sirven igual en cualquier VM Ubuntu.

### B1. Hetzner Cloud (~3.79€/mes, sin líos de capacidad)

1. Cuenta en https://www.hetzner.com/cloud/ (pide tarjeta, cobra desde el minuto uno).
2. New Project → Add Server → Location Falkenstein/Núremberg → Image Ubuntu 24.04 → Type CX22 (2
   vCPU/4GB — evita el CX11 de 1vCPU/2GB, va justo con Chromium) → añade tu clave SSH → Create.
3. Copia la IP pública.

### B2. Oracle Cloud Always Free (gratis, pero puede dar problemas de registro/capacidad)

1. https://www.oracle.com/cloud/free/ → registro con verificación de identidad.
2. Compute → Instances → Create instance → Image Ubuntu aarch64/ARM → Shape `VM.Standard.A1.Flex` (2
   OCPU/12GB) → añade tu clave SSH → Create.
3. Si da "Out of capacity": prueba otra región o reinténtalo más tarde. Alternativa de respaldo dentro
   de Oracle: shape `VM.Standard.E2.1.Micro` (x86, 1GB RAM, más ajustado).

### B3. Confirmarme estos datos y hago el resto (Hetzner u Oracle)

Dime: IP pública, ruta a la clave privada SSH (o contraseña si te la mandaron por email), y el usuario
por defecto (`root` en Hetzner, `ubuntu` en Oracle). Con eso me conecto por SSH desde tu propio PC y
hago: `deploy/package.sh` (empaqueta el proyecto sin `.venv`/`.env`/db) → `scp` del paquete y de tu
`.env` (con el token nuevo) a la VM → `deploy/setup_vm.sh` en la VM (instala Python, Playwright,
registra el bot como servicio systemd) → verifico que responde en Telegram.

### Comandos útiles (VM ya desplegada)

```bash
ssh -i /ruta/a/tu/clave usuario@IP_PUBLICA
journalctl -u surebets -f          # logs en vivo
sudo systemctl restart surebets    # reiniciar tras un cambio de código
```
