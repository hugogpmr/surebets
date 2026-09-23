# Límites de apuesta y anulación por casa (estudio del 2026-09-20)

Objetivo: que entre "pongo la apuesta en una casa" y "pongo la otra" no se rompa la surebet porque
(a) la cuota cambió, (b) había un límite que no vi, o (c) la segunda casa no acepta la apuesta.

**Nivel de fiabilidad** de cada dato: ✅ = leído en la fuente oficial de la casa (T&C / ayuda);
🟡 = solo en snippets de búsqueda o webs de terceros (reseñas), sin abrir la fuente oficial;
❓ = no encontrado. Varias webs oficiales (bet365, Sportium, Codere, William Hill) devuelven 403 o cargan por JS
a un lector automático, así que lo marcado 🟡/❓ hay que comprobarlo una vez a mano.

---

## 1. Tabla resumen: ¿se puede anular? ¿hay cash out?

| Casa | Anular apuesta ya confirmada | Cash out | Plataforma (según el proyecto) | Fiab. |
|---|---|---|---|---|
| **Winamax** | **Sí, 2 min tras validarla, importe íntegro.** Solo pre-partido, máx. **5 veces cada 24 h**. No en directo, no en sistema, no en combinadas con Combo Booster, no si ya empezó algún evento, no si hubo cashout parcial | Sí (total/parcial, irreversible una vez validado) | propia | ✅ |
| **bet365** | No. Una vez confirmada no se cancela | Sí ("Cerrar apuesta"), total/parcial; no en todos los mercados | propia | 🟡 |
| **Codere** | No ("no es posible anular apuestas"); solo puedes quitar selecciones *antes* de confirmar el boleto | Sí; no se puede cancelar un cash out ya confirmado | propia | 🟡 |
| **Sportium** | No, una vez confirmada por el sistema | Sí (página `/cashout`) | propia | 🟡 |
| **Jokerbet** | No encontrado → asumir que **no** | Sí, pre-partido y directo | Altenar | 🟡 / ❓ |
| **Betfair** | **Exchange:** la parte *no igualada* se cancela libremente; la parte ya igualada, no. **Sportsbook:** no encontrado → asumir que no | Sportsbook: sí, pero "no garantizado", puede fallar si las cuotas se mueven y te ofrece un importe nuevo. Exchange: se "cierra" con apuesta contraria | propia | 🟡 |
| **Speedybet** | No ("no es posible cancelar una apuesta") | Sí, pre-partido y directo, simples y múltiples; no en freebets | Kambi (grupo Paf) | ✅/🟡 |
| **Paf** | No, salvo "error aceptado" (T&C 3.2) | Sí, pero sujeto al mismo retraso de aceptación; si en ese retraso cambian las cuotas o desaparece la oferta, **se rechaza**. No con bonos activos ni freebets | Kambi | ✅ |
| **LeoVegas** | No encontrado → asumir que no (misma plataforma Kambi que Paf) | Sí, total y parcial; no en freebets | Kambi | 🟡 |
| **Bwin** | No, una vez aceptada | Sí ("Cobro inmediato", también parcial vía "Editar apuesta"). No con sistema, freebets, bonos ni Protektor. Si tras pedirlo el valor **baja**, se bloquea salvo que tengas activado "aceptar todos los pagos"; si sube, siempre se acepta | propia (Entain) | ✅ |
| **PokerStars** | No; solo se anula una selección de una combinada si el mercado se anula (cuota 1.0) | Sí ("Cerrar apuesta"); no si el mercado está suspendido | propia | 🟡 |
| **Interwetten** | No encontrado → asumir que no | Sí (fútbol, tenis, baloncesto, balonmano...) | propia | 🟡 / ❓ |
| **888sport** | Su ayuda tiene un artículo "Cancelar una apuesta", que no pude abrir; solo consta que la casa se reserva anular apuestas en ciertos supuestos → asumir que **tú no puedes** | Sí, pre-partido y directo, simples y múltiples (botón amarillo en "Mis apuestas"); parcial no confirmado | propia (888) | 🟡 / ❓ |
| **William Hill** | No salvo contactar de inmediato con atención al cliente ("solo excepcionalmente") | Sí ("Cerrar apuesta") | propia | 🟡 |

Notas:
- **Únicamente Winamax ofrece anulación real sin coste.** En todas las demás, si te equivocas, tu única salida es cash out
  (que te cuesta el margen de la casa) o quedarte con la apuesta abierta.
- **William Hill**: una búsqueda decía que ya no opera en España y otra que sigue con licencia DGOJ vigente (WHG Spain).
  Sin resolver, compruébalo antes de contar con ella.
- **"Sport" = 888sport** (confirmado por el usuario); añadida a la tabla y a los límites.
- La regla de "cash out tiene retraso y puede rechazarse" es **de Kambi** (Paf, LeoVegas, Speedybet): cuando más lo
  necesitas (cuota moviéndose) es cuando más probable es que te lo rechacen.

---

## 2. Cómo ver el límite (apuesta máxima) *antes* de apostar

Ninguna casa publica una tabla de máximos: depende del deporte, la liga, el mercado, la cuota **y de tu cuenta**.

| Casa | Qué se sabe | Cómo verlo |
|---|---|---|
| **bet365** | Si el importe excede el máximo, aparece un aviso en el boleto ✅ (ayuda oficial). Pueden aplicar la limitación de forma silenciosa reduciendo el máximo al confirmar 🟡 | Mete un importe muy alto en el boleto, **sin confirmar**, y lee el aviso |
| **Paf** | T&C ✅: mínimo 0,10 €, **máximo 1.000 € por apuesta salvo excepciones por mercado**; pago neto máx. 200.000 €. Pueden **aceptar la apuesta con el importe reducido** en vez de rechazarla (T&C 3.5) | Igual: importe alto en el boleto y leer el aviso; **comprobar en el historial cuánto se aceptó de verdad** |
| **Speedybet, LeoVegas** | Misma plataforma Kambi → es razonable esperar reglas parecidas a Paf (sin verificar, salvo Speedybet cuyos T&C tienen versión propia 2.0) | Igual |
| **Codere** | "Depende de la cuota, del evento y del tipo de apuesta" 🟡; mínimo 0,20 € en combinadas | Igual |
| **Betfair Exchange** | El límite es la **liquidez visible**: solo puedes igualar lo que otros ofrecen a esa cuota | Mirar el importe disponible en la columna de la cuota. Lo no igualado queda pendiente y se cancela |
| **888sport** | Sus reglas ✅ limitan el **pago** (ganancias liquidadas en un día), no la apuesta: tope general **250.000 €/día** y topes por deporte (fútbol grandes ligas 250.000 €, tenis Grand Slam desde 3.ª ronda 150.000 €, NBA/Euroliga 100.000 €, mayoría de competiciones femeninas 10.000 €). Pueden imponer **límites personales más bajos** por tipo de apuesta, liga o evento; las ganancias por encima del límite **no se pagan** | Igual que el método genérico; en mercados nicho/ligas menores el tope es bajo, calcula `stake × (cuota−1)` contra él |
| **Winamax, Sportium, Jokerbet, Bwin, PokerStars, Interwetten, William Hill** | ❓ no encontrado en fuentes oficiales | Método genérico (arriba) |

Método genérico (no verificado casa por casa, pero inocuo porque no se confirma nada): añade la selección al boleto,
escribe un importe absurdo (p. ej. 99999) y **no pulses "Apostar"**; la mayoría de casas responden con
"importe máximo: X". Apúntalo por casa + mercado.

**Señal de alarma con Paf/Kambi**: sus T&C (3.4.4) dicen expresamente que pueden rechazar o limitar apuestas para
"proteger a Paf... si se sospecha... que esté realizando arbitraje". Es la casa con la redacción más explícita
contra surebets; trátala como la más probable de limitarte.

### Cómo dimensionar la apuesta con los límites

1. Calcula las stakes ideales de la surebet.
2. Comprueba el límite de cada pata. La pata con menor límite manda: **reescala todas las stakes** con
   `factor = límite_pata / stake_ideal_pata` (el menor de todos) para mantener el mismo beneficio %.
3. Si una casa te acepta "parcialmente" (Paf puede), recalcula y **cubre la diferencia** en la otra casa o con cash out.

---

## 3. Orden en el que colocar las apuestas

**Regla general**: coste esperado de deshacer = P(la 2.ª pata falla) × coste de deshacer la 1.ª. Elige el orden que
lo minimice.

1. **Primero la pata que sale gratis (o casi) de deshacer, después la pata "difícil".**
   - **Winamax primero** (pre-partido): si la otra casa rechaza, la anulas en <2 min y recuperas todo. Es exactamente
     lo que haces ahora, y es lo óptimo. Limitaciones: solo pre-partido, 5 anulaciones/24 h, no en directo, y tienes
     que **acordarte de anular antes de 2 minutos**.
   - **Betfair Exchange**: si pones tu oferta a la cuota exacta y queda **sin igualar**, la cancelas gratis. Es una
     pata "primera" muy buena. Vigila que una igualación **parcial** te deja exposición: cancela el resto y cubre lo
     igualado en la otra casa.
2. **Si ambas cuestan lo mismo deshacerse** (p. ej. bet365 + Codere; las dos solo con cash out): pon **primero la
   pata más arriesgada** (más retraso, mercado nicho con límite bajo, cuota que se mueve rápido) y **última** la
   más segura. Así, si la arriesgada falla, todavía no has apostado nada.
3. **Casas con retraso de aceptación (Kambi: Paf, LeoVegas, Speedybet; en general todas en directo)**: son patas
   "difíciles" → van en su posición de riesgo y **nunca en directo** salvo que aceptes el riesgo de cuota movida.
4. **Desactiva "aceptar cambios de cuota"** en la casa de la 2.ª pata (o revisa la cuota final en el historial).
   Si acepta un cambio a peor, tienes una apuesta abierta con beneficio roto sin darte cuenta.
5. **Comprueba siempre el historial de apuestas** tras apostar: Paf dice expresamente que la apuesta no existe hasta
   que aparece en el historial, y puede haber aceptado menos importe.

### Si algo sale mal, ¿qué hago?

| Situación | Acción |
|---|---|
| 2.ª casa rechaza y la 1.ª es Winamax pre-partido | Anular en Winamax (dentro de 2 min) → pérdida 0 |
| 2.ª casa rechaza y la 1.ª es Exchange sin igualar | Cancelar oferta → pérdida 0 |
| 2.ª casa rechaza y la 1.ª es otra | Reintenta 1–2 veces con el límite que te dice; si no, cash out de la 1.ª (pierdes el margen del cash out) o intenta cubrir en una tercera casa |
| 2.ª casa acepta menos importe | Recalcula y cubre el resto en otra casa o cash out parcial de la 1.ª |
| 2.ª casa acepta con cuota peor | Recalcula: si sigue >0 déjala; si no, cash out de la más cara de deshacer o cubre con una 3.ª casa |
| Directo | Sin anulación posible en ninguna casa → solo entrar si ambas patas se pueden confirmar casi a la vez |

---

## 4. Pendiente / siguientes pasos posibles

- Verificar a mano (una sola vez) lo marcado 🟡/❓: anulación en Jokerbet, Interwetten, LeoVegas; máximos de
  Winamax/Sportium/Bwin/PokerStars; estado de William Hill en España.
- **Automatizar el límite: comprobado el 2026-09-20, las APIs públicas NO lo exponen.**
  - **Kambi** (`pafes`, `leoes`): `listView` y `betoffer/event/{id}` traen solo `betOfferType`, `cashOutStatus`,
    `criterion`, `oddsStats`, `tags` y, por selección, `odds`, `line`, `status`, `changedDate`. Cero campos de
    apuesta máxima/stake/límite. Probé rutas típicas de límites (`betslip/v2/limits.json`, `coupon/limits.json`,
    `settings.json`) y dan 404.
  - **Altenar** (Jokerbet, Pastón, Betway): `GetEvents` y `GetEventDetails` traen mercados (`typeId`, `sv`, `isBB`...)
    y cuotas (`price`, `oddStatus`), sin ningún campo de límite ni de cash out. Endpoints tipo `GetBetLimits` o
    `GetSettings` dan 404.
  - El máximo real se calcula al validar el boleto con **sesión iniciada** (depende de tu cuenta), así que solo
    saldría de las APIs autenticadas de cada casa. Eso implicaría usar tus credenciales; no lo he hecho ni lo haré.
- **Sí aprovechable de Kambi**: `cashOutStatus` (ENABLED/…) por oferta y selección → el panel puede indicar si la
  pata en Paf/LeoVegas tiene cash out disponible (o sea, si hay salida de emergencia), y `changedDate` por selección
  → mide cuánto hace que se movió la cuota (cuota "vieja" = mayor riesgo de que ya haya cambiado).
- **Implementado (2026-09-20)**:
  - [docs/limites.json](docs/limites.json): tabla manual (casa + deporte/mercado opcionales → `max_stake`). Viene con
    Paf a 1.000 € (T&C oficiales); el resto lo rellenas tú con el método del boleto.
  - La calculadora de reparto del panel reduce el **total** invertido si alguna pata supera su máximo (mismo margen,
    menos dinero) y avisa de las casas sin límite anotado.
  - Cada pata muestra `cash out ✓ / sin cash out` (solo Kambi: Paf, LeoVegas) y `cuota movida hace N min`
    (`changedDate`). Estos campos aparecen en `data.json` tras el próximo escaneo.
  - No hay aún equivalente en el motor Python (alertas): los límites solo se aplican en el panel.

## Fuentes

- Winamax, Anular apuesta (oficial): https://www.winamax.es/anular-apuesta?LICENSE=ES
- Paf, T&C de apuestas v2.1 (Kambi): https://static.kambicdn.com/terms-and-conditions/com/paf/es_ES.pdf
- Bwin, Cobro inmediato (oficial): https://www.bwin.es/es/sports/news/utilizar-cobro-inmediato/
- Speedybet, T&C v2.0: https://static.kambicdn.com/terms-and-conditions/es/paf/pafspeedybetes/2.0_Speedybet.es_ES.pdf
- bet365, Cerrar apuesta (ayuda): https://help.bet365.es/es/product-help/sports/betting-features/cash-out/cash-out
- bet365, mín./máx. de apuesta (ayuda): https://help.bet365.com/s/es/sports/min-max-stake
- Codere, FAQ y reglas: https://www.codere.es/ayuda/preguntas-frecuentes
- Sportium, FAQ y cashout: https://www.sportium.es/faq/apuestas · https://www.sportium.es/cashout/apuestas
- Betfair, cancelar apuesta en Exchange: https://support.betfair.com/es/app/answers/detail/a_id/3247/
- 888sport, límites máximos de pago: https://www.888sport.es/como-apostar/reglas-apuestas/limites-maximos-de-pago/
- William Hill, cancelar/cambiar apuesta: https://help.williamhill.es/hc/es/articles/27947556307485--C%C3%B3mo-cancelo-cambio-mi-apuesta
