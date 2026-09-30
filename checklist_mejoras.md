# Checklist de mejoras (2026-09-29)

Marca `[x]` al completar. Los puntos con ⭐ son los recomendados para empezar.

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
- [ ] 12. ⭐ Backtest con histórico: guardar cada surebet detectada y comprobar si la cuota seguía viva o era error de lectura; calibrar filtros con datos reales.
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
