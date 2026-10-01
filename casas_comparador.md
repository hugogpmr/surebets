# Casas del comparador (casasdeapuestas.com)

Lista para decidir con qué casas nos quedamos. **Marca con `[x]` las que quieres mantener y deja
`[ ]` las que quieres quitar**, y dime que ya está: las quito del bot (`EXCLUDED_BOOKIES` en
`providers/casasdeapuestas.py`).

Datos sacados el 2026-10-01 de la caché real de la VM (las ligas leídas en las últimas 2 h) y de
`data/surebets.db` de la VM.

## Antes de elegir: cómo funciona este comparador

- **Solo publica la MEJOR cuota de cada resultado**, no la tabla entera de casas. Por eso una casa
  pequeña aparece poco: solo cuando es la que mejor paga. Quitar una casa no destapa la segunda mejor:
  ese resultado simplemente se queda sin lectura del comparador en ese partido.
- **El criterio que de verdad importa: ¿tienes cuenta (o la vas a abrir) en esa casa?** Una surebet con
  una casa donde no puedes apostar no sirve de nada y solo mete ruido en Telegram.
- Las casas con fuente directa (columna "Directa") siguen leyéndose por su propia API aunque las quites
  aquí; solo se deja de usar su lectura del comparador. Ojo: hoy, desde la VM, la directa de William
  Hill, Winamax, bwin, Sportium y Versus no funciona, así que para esas el comparador es lo único que
  llega.

## Columnas

- ⭐ = está en tu lista de casas objetivo del 20-sep.
- ⚠️ = no está en la lista de licencias DGOJ que comprobamos a mano el 16-sep. Seguramente tenga licencia,
  pero no se ha verificado.
- **Mercados / Partidos**: lo que aporta ahora mismo (solo cuando es la mejor cuota).
- **Margen**: margen típico de la casa en 1X2, ganador o más/menos 2,5. Más bajo = paga mejor.
  Vacío = pocos datos.
- **Surebets**: en cuántos avisos ha salido del 27-sep al 1-oct. **Incluye las falsas** de antes de
  los arreglos del 30-sep y el 1-oct, así que sirve para ver cuánto pesa cada casa, no para medir calidad.

| Mantener | Casa | Clave | ⭐ | Directa | Mercados | Partidos | Margen | Deportes principales | Surebets | Notas |
|---|---|---|---|---|---|---|---|---|---|---|
| [x] | Jokerbet | `jokerbet` | ⭐ | sí | 4826 | 147 |  | fútbol, baloncesto | 262 |  |
| [x] | Bet365 | `bet365` | ⭐ | — | 4511 | 149 | 5,6 % | fútbol, baloncesto, tenis | 246 | Sin fuente directa (Cloudflare): solo llega por aquí. |
| [x] | Casino Gran Madrid (CGM Apuestas) ⚠️ | `cgmapuestas` |  | — | 3995 | 164 | 7,6 % | fútbol, baloncesto | 191 | Solo llega por aquí. Margen alto (7,6 %). |
| [x] | 888sport | `888sport` |  | sí | 2968 | 258 |  | fútbol, baloncesto, tenis | 866 | Muchas de sus surebets antiguas eran el hándicap de 3 vías (arreglado el 30-sep). |
| [x] | Interwetten ⚠️ | `interwetten` | ⭐ | — | 2065 | 298 | 7,1 % | fútbol, hockey, baloncesto | 243 | Sin fuente directa (Cloudflare): solo llega por aquí. |
| [x] | Betfair | `betfair` | ⭐ | sí | 1927 | 289 |  | fútbol, tenis, baloncesto | 1199 | Directa bloqueada por Cloudflare: solo llega por aquí. Muchas de sus surebets antiguas eran el hándicap de 3 vías (arreglado el 30-sep). |
| [x] | 1xBet | `1xbet_es` |  | — | 1746 | 303 | 5,4 % | fútbol, baloncesto, tenis | 433 | Solo llega por aquí. |
| [x] | Winamax | `winamax` | ⭐ | sí | 1471 | 205 | 6,5 % | fútbol, balonmano, baloncesto | 61 | La directa no funciona desde la VM: esto lo cubre. |
| [x] | Betway | `betway` |  | sí | 1342 | 150 |  | fútbol, baloncesto | 377 |  |
| [x] | OlyBet (Suertia) ⚠️ | `olybet` |  | — | 933 | 126 |  | hockey, baloncesto, fútbol | 47 | Su hándicap de tenis venía mal (arreglado hoy). Directa bloqueada (WAF). |
| [x] | Retabet | `retabet` |  | — | 806 | 178 | 7,3 % | fútbol | 53 | Solo llega por aquí. Solo fútbol. |
| [x] | William Hill | `williamhill` | ⭐ | sí | 674 | 153 | 5,6 % | baloncesto, tenis, hockey | 86 | La directa no funciona desde la VM (403): esto lo cubre. |
| [x] | Yosports | `yosports` |  | sí | 561 | 75 | 10,2 % | baloncesto, fútbol, NFL | 25 |  |
| [x] | Casumo ⚠️ | `casumo` |  | — | 450 | 42 |  | baloncesto, tenis, fútbol | 61 |  |
| [x] | Paston | `paston` |  | sí | 449 | 80 |  | fútbol, baloncesto | 83 |  |
| [x] | eBingo ⚠️ | `ebingo` |  | — | 420 | 89 |  | fútbol, béisbol, baloncesto | 52 |  |
| [x] | iJuego ⚠️ | `ijuego` |  | — | 413 | 64 |  | fútbol, béisbol, baloncesto | 11 |  |
| [x] | Bwin | `bwin` | ⭐ | sí | 339 | 115 |  | fútbol, NFL, baloncesto | 152 | La directa no funciona desde la VM: aquí cubre algo. |
| [x] | Golden Bull ⚠️ | `goldenbull` |  | — | 291 | 51 |  | fútbol, NFL, tenis | 38 |  |
| [x] | LeoVegas | `leovegas` | ⭐ | sí | 266 | 45 | 10,2 % | fútbol, balonmano, NFL | 39 |  |
| [x] | Paf | `paf` | ⭐ | sí | 241 | 29 |  | fútbol, tenis | 387 |  |
| [x] | Golden Park ⚠️ | `goldenpark` |  | — | 234 | 41 |  | fútbol, tenis | 33 | Su hándicap de tenis venía mal (arreglado hoy). |
| [x] | Speedybet | `speedybet` | ⭐ | sí | 205 | 45 |  | fútbol, tenis, balonmano | 35 |  |
| [x] | Casino Barcelona ⚠️ | `casino_barcelona` |  | — | 170 | 19 |  | fútbol, baloncesto, hockey | 6 |  |
| [x] | Kirolbet | `kirolbet` |  | sí | 169 | 77 |  | fútbol | 3 |  |
| [x] | Marca Apuestas | `marcaapuestas` |  | sí | 155 | 51 |  | fútbol, NFL, tenis | 23 |  |
| [x] | Codere | `codere` | ⭐ | — | 85 | 61 |  | fútbol, NFL, tenis | 13 | Sin fuente directa (Akamai): solo llega por aquí. |
| [x] | Versus | `versus` |  | sí | 85 | 32 |  | fútbol, balonmano, béisbol | 15 | La directa falla a menudo desde la VM. |
| [x] | Yaass Casino ⚠️ | `yaasscasino` |  | — | 76 | 32 |  | fútbol, tenis | 19 |  |
| [x] | Bet777 | `bet777` |  | sí | 72 | 54 |  | fútbol | 227 | Casi todo llega por su API directa; aquí aporta poco. |
| [x] | Sportium | `sportium` | ⭐ | sí | 71 | 21 | 9,1 % | hockey, fútbol, NFL | 5 | La directa no funciona desde la VM: aquí cubre algo. |
| [x] | Enracha ⚠️ | `enracha` |  | — | 67 | 28 |  | fútbol, NFL, baloncesto | 22 |  |
| [x] | Zebet | `zebet` |  | sí | 58 | 13 |  | baloncesto | 0 |  |
| [x] | Sol Casino ⚠️ | `solcasino` |  | — | 52 | 12 |  | fútbol | 0 |  |
| [x] | Luckia | `luckia` |  | — | 37 | 18 |  | fútbol, tenis | 96 | Solo llega por aquí. Muy poca cobertura ahora mismo. |
| [x] | DAZN Bet ⚠️ | `daznbet_es` |  | — | 17 | 14 |  | baloncesto, fútbol, tenis | 6 | Llegaba con otro nombre que desde Altenar: ya unificada como la misma casa. |
| [x] | TonyBet ⚠️ | `tonybet` |  | — | 8 | 5 |  | NFL, fútbol | 1 |  |
| [ ] | Betfair Exchange ⚠️ | `betfair_exchange` |  | — | 4 | 4 |  | fútbol | 0 | **Ya excluida**: es la cuota bruta del Exchange, sin descontar la comisión. |

Casas directas que no aparecen en el comparador (no se ven afectadas): Betinia, Botemanía (Altenar/Kambi).

## Mi recomendación

1. Quita todas las casas en las que no tengas ni vayas a abrir cuenta.
2. De tus ⭐, bet365, Codere e Interwetten **solo llegan por aquí**: si te interesan, tienen que
   quedarse.
3. Las casas de casino con muy poca cobertura (Sol Casino, TonyBet, Yaass Casino, Enracha, Casino
   Barcelona, iJuego...) son buenas candidatas a quitar si no tienes cuenta: aportan muy pocos
   mercados y suelen limitar rápido.
