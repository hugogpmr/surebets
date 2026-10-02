# Checklist de mejoras (2026-09-29)

Marca `[x]` al completar. Los puntos con ⭐ son los recomendados para empezar.

## Hoja de ruta (revisión general del 2026-10-01)

Diagnóstico con datos reales de `data/surebets.db` (27-sep a 1-oct): el límite no es el número de
casas sino (1) avisos con errores de lectura, (2) latencia (ciclo cada 12 min, Chromium arrancado de cero
cada vez: las surebets reales duran minutos), (3) 7 fuentes a 0 en la VM por la IP de centro de datos y
(4) las cuentas limitadas, que son el recurso escaso de verdad. Decisión del usuario: las surebets con
pata de comparador SE AVISAN igual (comprobó a mano que sus cuotas coinciden con la casa oficial).

### Fase 0 — arreglos rápidos (hecho y desplegado en la VM el 2026-10-01)
- [x] `data/surebets.db` fuera de git: crecía ~11 MB/día (55 MB el 1-oct) y GitHub rechaza ficheros de
      más de 100 MB → el push del ciclo iba a romperse hacia el 5-oct. Se queda solo en la VM (copia:
      `/root/surebets.db.bak-2026-10-01`). El push del ciclo bajó a ~3 s.
- [x] Desplegar el backtest (punto 12) en la VM: ya graba en `cache/backtest.db` (primer ciclo: 453 episodios).
- [x] Tenis: Goldenpark/Olybet publican en el comparador el hándicap de SETS ±1.5 como "hándicap de
      juegos" (y con el signo cambiado) → surebets falsas del 18-23 % del 1-oct. Descartarlo.
- [x] Edad máxima de las cuotas cacheadas del comparador: 8 h → 2 h (red de seguridad si el ciclo lento falla).
- [—] Limpiar el historial de git: descartado por el usuario (2026-10-01), no hace falta: ya no crece.

### Antes de la Fase 1 — quedarnos con las casas que interesan
- [x] (2026-10-01: quitadas 11 + Betfair Exchange, CGM se queda de momento) El usuario marca en [casas_comparador.md](casas_comparador.md) qué casas del comparador se quedan
      (criterio: tener o ir a abrir cuenta ahí). Luego se ponen las descartadas en `EXCLUDED_BOOKIES`
      (`providers/casasdeapuestas.py`) y se despliega.
- [x] Betfair Exchange del comparador excluido (cuota bruta sin comisión) y DAZN Bet unificado
      (`daznbet_es` = `daznbet`), 2026-10-01.
- [ ] Con la lista cerrada: verificar a mano las licencias DGOJ de las que se queden con ⚠️ y añadirlas
      al panel (`docs/app.js`).

### Fase 1 — Betfair Exchange: DESCARTADA (2026-10-01)
El usuario no quiere apostar contra otros jugadores (ni back-lay ni Exchange como casa). Se llegó a
crear la Delayed App Key y a verificar el provider en vivo (16 partidos de LaLiga), pero se quitó del
escaneo. El código (`providers/betfair_exchange.py`) se conserva por si se reconsidera.

### Fase 2 — motor continuo (velocidad)
- [x] Un servicio permanente con un trabajador por fuente, cada una a su ritmo (2026-10-01:
      `engine/live.py` + `scripts/run_live.py`, servicio `surebets-live`; ciclo lento seguido;
      panel a GitHub cada 10 min). Medido antes del cambio: Altenar ~300 s por lectura (1.350
      partidos), 888sport ~200 s, Kambi ~160 s, cruce ~24 s.
- [!] **3ª prueba (2026-10-01 22:28 → 10-02 12:09, con caché de fichas)**: estable (sin OOM, swap ~600 MB)
      pero se reinició 52 veces por pasar de 2 GB, al final cada 10 min: el volumen subió (viernes: 262k
      mercados, Altenar 176k, cruce 181 s con la CPU llena). En la práctica, un análisis cada ~10 min:
      sin ventaja sobre el ciclo de 12. Vuelto al ciclo de 12 min. Con 4 GB / 2 vCPU no da: hace falta
      VM más grande o leer menos (recortar mercados que nunca dan surebets, con datos del backtest).
- [!] **En pausa por memoria (2026-10-01)**: probado 2 veces en la VM. Funciona (avisos cada 1-2 min,
      sin re-avisos al arrancar) pero en una VM de 4 GB agota la swap: 1ª prueba swap 100 % en 35 min;
      2ª (malloc_trim + MALLOC_ARENA_MAX=2 + menos hilos) aguantó 40 min sin reiniciarse pero la swap
      seguía subiendo (380 → 1.075 MB). Vuelto al ciclo de 12 min. El ciclo lento SÍ se queda seguido.
      Decisión pendiente del usuario: subir la VM a 8 GB (y reactivar con
      `systemctl disable --now surebets-fast.timer && systemctl enable --now surebets-live surebets-publish.timer`)
      o adelgazar antes lo que se guarda (siguiente punto).
- [x] (2026-10-02, solo en modo continuo: `providers/detail_cache.py`; partidos a <6 h cada vuelta, 6-24 h cada 20 min, más lejos cada 45 min; navegadores a la vez 3 → 2) Altenar/Kambi/comparador por ventana de kickoff: fichas de los partidos de las próximas horas en
      cada vuelta, las de dentro de varios días cada 30-60 min (hoy Altenar relee los 1.350 cada vez).
- [ ] Navegadores persistentes con la sesión cargada en vez de ~8 Chromium nuevos por ciclo (CPU/RAM/OOM).
- [ ] Cuotas en memoria y recálculo solo del partido que cambia → aviso en segundos, con relectura de las
      patas justo antes de avisar. Publicar el panel sin git en cada ciclo.

### Backtest del 1-2 oct (18 h, 382 surebets válidas, 359 avisadas)
- Duración real: mediana 9,5 min; las de solo fuentes directas 3,4 min; 25 % desaparecen en <= 2 min.
  Con el ciclo de 12 min casi todas las directas llegan tarde: argumento de datos para la Fase 2.
- Margen > 5 %: casi nunca terminan por movimiento de cuota (5-15 %: 10 de 35; > 15 %: 0 de 25) → errores.
- [x] Fútbol "ML" del comparador = 1X2 sin la cuota del empate (14-25 %, varias avisadas). Arreglado.
- [x] Tarjetas de Bet777 = solo amarillas, cruzadas con el total de tarjetas (8 %, nunca se movió). Separadas (YELLOW_).
- [ ] Tarjetas Altenar contra Kambi: 12 casos, margen 3,2 %, ninguno terminó por movimiento de cuota.
      Sospechoso (¿cuentan distinto la roja?), sin probar. Seguir con el backtest antes de tocar nada.
- [ ] São Paulo-Santos AH -0.5 (bet365 contra Winamax) vivo 13 h al 5,8 %: revisar el hándicap de Winamax.

### Avisos (detectado 2026-10-02)
- [ ] Agrupar avisos: 290 avisos de 86 partidos en 8 h (modo antiguo, 1-oct), hasta 26 del mismo partido
      (un aviso por cada línea de más/menos o hándicap, y otro cada vez que el margen cambia 0,5 puntos).
      Un mensaje por partido con todas sus surebets y re-avisar solo si mejora de verdad.

### Fase 3 — nodo en casa (webs que la VM no puede leer)
- [ ] Mini PC / Raspberry Pi en la conexión de casa con las fuentes de navegador (Sportium, Versus, bwin,
      Winamax, William Hill), mandando sus lecturas a la VM por Tailscale. Es tu conexión, no un proxy.

### Fase 4 — cuentas y ejecución
- [ ] Botón "he apostado" en Telegram, registro de beneficio y de límites por casa (puntos 18-20).
- [ ] Ordenar surebets por lo que "gastan" de cada cuenta, no solo por margen (evitar mercados que delatan).

## A. Fiabilidad de la VM
- [ ] 1. Diagnosticar el bloqueo por IP de datacenter (Sportium, Versus, Betfair, bwin, William Hill, Winamax dan 0 mercados en la VM). Opciones: escaneo desde tu PC, otra VM con IP menos "datacenter". Sin proxies ni evasión.
- [x] 3. ⭐ Alerta a Telegram de "fuente muerta" y de ciclo muerto por OOM: hecho, desplegado y probado en la VM (2026-09-30), enviando al supergrupo "admin surebets".
  - [ ] 3b. Alternativa al canal: un tema nuevo dentro del grupo de surebets, creado por el bot y cerrado para que solo escriban los admins. Limitación: Telegram no permite ocultar un tema a los miembros del grupo, así que lo leería todo el grupo. Pendiente de decidir; no implementado.
- [ ] 4. Verificar que el swap y el OOM quedaron arreglados (`dmesg`, `journalctl ... Failed with result`) tras varios días.
- [ ] 5. Diagnosticar de verdad (con captura, desde la VM) la ficha de Sportium y el DC de PokerStars, ambos desactivados sin causa raíz.

## B. Cobertura de mercados y casas
- [ ] 6. Betfair Exchange con Delayed Key gratuita (falta que generes la clave) + ángulo back-lay en el motor.
- [x] 7. Más ligas en 888sport, Zebet, Versus y Marca Apuestas (2026-09-29): 888 todas las ligas por listado diario; Zebet +11 ligas (solo 1X2) + NHL; Marca y Versus +4 ligas cada una (con 9 el ciclo de la VM subía a 330 s). Ojo: Versus/Sportium no leen desde la VM (IP de centro de datos).
- [x] 8. Mercados extra de Zebet y Bet777 (2026-09-29): Zebet goles por equipo, primer gol y BTTS 1ª mitad (el más/menos por mitades ya estaba); Bet777 primer equipo en marcar. El resto de mercados de Bet777 auditados no tienen socio con el que cruzar.
- [ ] 9. Pinnacle vía pinnapi como señal "sharp" de coherencia en `engine/quality.py`.
- [~] 10. Tenis y baloncesto en más casas directas: HECHO en 888sport (2026-09-29). NO hecho en Zebet (su listado no trae las cuotas en las clases del fútbol) ni en PokerStars (DOM pesado, ya es lo más lento de la VM).
- [x] 11. Más deportes en Altenar/Kambi (2026-09-29): hockey, béisbol, balonmano (Altenar+Kambi) y voleibol (solo Altenar + Bet777, Kambi no lo lista). Bet777 también hockey, béisbol y voleibol. Vigilar 429 de Kambi en la VM.

## C. Calidad de las surebets
- [x] 12. ⭐ Backtest con histórico (2026-10-01): cada surebet detectada (también las descartadas por error de datos) se guarda como un episodio en `cache/backtest.db` (fuera de git), con la cuota de cada pata al empezar, al máximo/mínimo y al terminar, y el motivo del fin: `cuota_movida` (real, no es error), `relevo_de_casas`, `pata_desaparecida`, `mercado_desaparecido`, `partido_empezado`, `sin_datos`. Informe: `python scripts/backtest_report.py [--days N] [--csv f.csv]`. Sin esperar ciclos: no cambia cuándo se avisa. Pendiente de desplegar en la VM; los datos útiles llegan tras unos días de ciclos. Código en `engine/backtest.py`.
- [ ] 13. Filtro por antigüedad de cuota (Kambi expone `changedDate` por outcome).
- [ ] 14. Penalizar cuotas de comparador cerca del kickoff (divergen hasta ~7%).
- [ ] 15. Puntuación de confianza por casa según su tasa histórica de cuotas que desaparecen o cambian.
- [ ] 16. Arreglar el matching de equipos parecidos ("América"/"América-MG"): competición + hora de inicio como criterio duro.
- [ ] 17. Cruce de selecciones nacionales (la tabla de alias solo conoce clubes).

## D. Utilidad para apostar
- [ ] 18. Calculadora de stakes con límites reales por casa (ir anotando el límite real al apostar en `docs/limites.json`).
- [ ] 19. Botón "he apostado" en Telegram/web: registrar apuesta, beneficio real y qué casas te limitan.
- [ ] 20. Tracking de bankroll y rentabilidad por casa y por tipo de mercado.
- [ ] 21. Ranking de surebets ponderando margen, liquidez y riesgo de anulación (solo Winamax permite cancelar).
- [ ] 22. Alertas priorizadas: solo margen mínimo y estables durante 2 ciclos; resto en resumen.
- [ ] 23. Enlaces directos al partido en cada casa dentro de la alerta.

## E. Velocidad
- [ ] 24. Arrancar el refine de PokerStars en cuanto Altenar/Kambi tengan sus listas de eventos (sin esperar a los detalles).
- [ ] 25. Escaneo por ventana de kickoff: más frecuencia para partidos a <2 h, menos para los de 5 días.
- [ ] 26. Reactivar los tiers de staleness de `engine/cache.py` (hoy el presupuesto lo cubre todo y no sirven).

## F. Mantenimiento
- [ ] 27. Tests de regresión con fixtures reales para los proveedores DOM.
- [ ] 28. Panel de salud en la web: última lectura por casa, mercados por ciclo, estado parked/activo.
- [ ] 29. Limpiar el repo: `surebets.tar.gz`, `.md` de estudio sueltos en la raíz y `__pycache__` a `docs/` o `.gitignore`.
- [ ] 30. Runbook único de la VM (deploy, timers, swap, claves) en un solo sitio.
