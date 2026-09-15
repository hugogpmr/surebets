# Surebets

Sistema propio de detección de arbitraje deportivo (surebets), pensado para arrancar con coste mínimo.

Basado en:
- [Arbitraje deportivo y surebets: guía técnica y práctica](<Arbitraje deportivo y surebets  guía técnica y práctica para montar un sistema asistido por IA.md>)
- [Cómo montar un sistema ligero de detección de surebets con coste mínimo](<Cómo montar un sistema ligero de detección de surebets con coste mínimo.md>)

## Arquitectura

```
engine/               motor matemático: detección de surebets, margen, cálculo de stakes, y el ciclo de
                      escaneo (scan.py) reutilizado tanto por main.py como por scripts/scan_once_action.py
providers/            fuentes de cuotas (interfaz OddsProvider). mock.py es un proveedor de ejemplo para pruebas.
storage/              SQLite: registro de oportunidades detectadas
bot/                  bot de Telegram (/hoy, /ahora, /stats)
main.py               orquestador de larga duración: fetch periódico -> detección -> guardado -> aviso (VM + systemd)
scripts/              scan_once_action.py: un solo ciclo de escaneo, pensado para GitHub Actions
.github/workflows/    workflow programado que ejecuta scripts/scan_once_action.py cada 15 min
```

El motor (`engine/`) no sabe nada de Telegram ni de scraping: por eso el mismo core podrá alimentar más adelante
un panel web sin reescribir la lógica de arbitraje.

## Puesta en marcha

```bash
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edita `.env`:
- `TELEGRAM_BOT_TOKEN`: crea un bot con [@BotFather](https://t.me/BotFather) en Telegram (`/newbot`) y pega el token aquí. **No lo compartas ni lo subas a git.**
- `TELEGRAM_CHAT_ID`: tu chat id (envía un mensaje a tu bot y consulta `https://api.telegram.org/bot<TOKEN>/getUpdates` para obtenerlo), para recibir avisos automáticos de nuevas surebets.
- `BANKROLL`: banca a repartir en cada oportunidad (por defecto 250€).
- `MIN_MARGIN`: margen mínimo para considerar una oportunidad relevante (por defecto 0.01 = 1%).

Arrancar:

```bash
.venv\Scripts\python main.py
```

Con el proveedor `mock` de ejemplo, el bot detectará una surebet ficticia (Djokovic/Alcaraz, cuotas 2.00/2.05) y
responderá a los comandos `/hoy`, `/ahora` y `/stats` en Telegram.

## Despliegue 24/7 (sin depender de tu PC)

Dos opciones documentadas paso a paso en [deploy/README_DEPLOY.md](deploy/README_DEPLOY.md):
GitHub Actions (gratis, sin tarjeta, solo avisos push) o una VM propia con systemd (Hetzner de pago,
u Oracle Cloud Always Free) con el bot completo incluyendo `/hoy`, `/ahora` y `/stats`.

## Tests

```bash
.venv\Scripts\python -m pytest
```

## Estado actual y próximos pasos

**Hecho (MVP fase 0):**
- Motor de arbitraje (`engine/arbitrage.py`) con tests, validado contra el ejemplo del documento base.
- Interfaz de proveedores de cuotas (`providers/base.py`) desacoplada, con un proveedor mock para probar el flujo completo.
- `engine/matching.py`: agrupa el mismo evento/mercado entre casas distintas (aunque el nombre del equipo varíe) y se queda con la mejor cuota de cada resultado antes de evaluar el arbitraje.
- Almacenamiento SQLite de oportunidades detectadas.
- Bot de Telegram con comandos `/hoy`, `/ahora`, `/stats` y avisos automáticos.

### Estado real de los scrapers (verificado en vivo, no teórico)

| Casa | Estado | Detalle |
|---|---|---|
| **Sportium** | ✅ Funciona (`providers/sportium.py`) | Playwright headless normal, sin trucos. 1X2 en vivo verificado. Over/under pendiente (línea y cuota concatenadas en el mismo texto del DOM). |
| **Betfair** | ✅ Funciona (`providers/betfair.py`) | Playwright headless normal. 1X2 en vivo verificado sobre el listado completo de LaLiga. |
| **Winamax** | ✅ Funciona (`providers/winamax.py`) | Playwright headless normal. Cuotas en coma decimal española, convertidas a float. 1X2 en vivo verificado. |
| **Kirolbet** | ⚠️ Implementado pero bloqueado (`providers/kirolbet.py`) | Akamai Bot Manager. Ver detalle abajo. |
| **Bwin** | ❌ Bloqueado | reCAPTCHA Enterprise invisible. Ver detalle abajo. |
| **Betsson** | ❌ Bloqueado | API antifraude propia. Ver detalle abajo. |
| **Codere** | ❌ Bloqueado a nivel de red | Denegación directa. Ver detalle abajo. |
| **Suertia (OlyBet)** | ❌ Bloqueado a nivel de red | "Access Denied" del proveedor. Ver detalle abajo. |
| **bet365** | ❌ No viable | Spinner infinito. Ver detalle abajo. |
| **Marca Apuestas** | ❌ Bloqueado | Cloudflare / 403 en API de cuotas. Ver detalle abajo. |
| **Luckia** | ❌ Bloqueado | Cloudflare "Just a moment...". Ver detalle abajo. |
| **Interwetten** | ❌ Bloqueado | Cloudflare "Just a moment...". Ver detalle abajo. |
| **William Hill** | ❌ Bloqueo explícito | Mensaje "Data Centre block". Ver detalle abajo. |
| **Paston, 888sport, PokerStars Sports, Zebet, Botemanía** | ❓ Sin confirmar | Cargan sin bloqueo aparente, pero no se llegó a localizar/confirmar la tabla de cuotas real en el DOM. Candidatos a re-probar. |

**3 casas reales funcionando** (Sportium, Betfair, Winamax) — suficiente para que el motor de arbitraje compare cuotas entre casas de verdad. Validado en vivo: el cruce de eventos agrupa correctamente el mismo partido aunque cada casa lo nombre distinto ("At. Madrid" / "Atl. Madrid" / "Atlético de Madrid"), y **dos bugs reales de cruce de eventos** se detectaron y corrigieron con datos en vivo (no en teoría):
- Comparar el nombre completo del evento como un solo string confundía partidos distintos que comparten texto (p.ej. "Atlético Madrid vs. Osasuna" con "Atlético Madrid vs. Real Madrid", por la palabra común "Madrid").
- La similitud de texto genérica para nombres de equipo cortos daba falsos positivos (p.ej. "Barcelona" y "Celta" resultaron tener suficiente parecido de letras como para confundirse cuando ambos jugaban contra el mismo rival).

La solución fue una tabla de alias curada a mano para los 20 equipos de LaLiga (`engine/team_aliases.py`), en vez de depender solo de similitud de texto genérica. Sin estas dos correcciones, el sistema habría mostrado "surebets" del 30-40% que en realidad eran errores de comparación, no oportunidades reales — habría sido activamente engañoso.

Detalle completo de cada bloqueo (qué se probó, por qué falló, posibilidades para arreglarlo) y el
trabajo pendiente sobre scraping: ver [checklist.md](checklist.md).

## Aviso legal

El arbitraje deportivo no es ilegal en España (Ley 13/2011), pero cada casa de apuestas puede limitar o cerrar
cuentas por sus propios términos y condiciones. El scraping debe hacerse de forma moderada y revisando los
términos de servicio de cada operador. Ver el documento base para más detalle.
