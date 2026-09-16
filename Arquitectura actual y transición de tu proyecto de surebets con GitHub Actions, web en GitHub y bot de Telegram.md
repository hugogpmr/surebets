# Arquitectura actual y transición de tu proyecto de surebets con GitHub Actions, web en GitHub y bot de Telegram

## 1. Contexto del proyecto

El proyecto actual combina tres piezas: un scraper de casas de apuestas, un bot de Telegram y una web/panel estático alojado en GitHub (GitHub Pages), con GitHub Actions como motor para ejecutar scripts periódicamente. Este documento resume cómo está montado ese esquema, por qué aparecen problemas (IP, límites de Actions) y cómo migrarlo a una arquitectura más estable manteniendo la web y el bot.

GitHub Actions está diseñado para CI/CD y tareas efímeras (tests, builds, despliegues), con límites de tiempo de trabajo por job (≈6 horas en runners hospedados por GitHub) y frecuencia mínima de disparo por cron (cada 5 minutos).  Esto lo hace poco adecuado para procesos que necesitan estar siempre encendidos (scraper continuo, bot en long polling), y los runners usan IPs de datacenter que pueden no coincidir con España, provocando bloqueos de acceso a casas que solo aceptan IP española.[^1][^2][^3][^4]

## 2. Arquitectura actual basada en GitHub Actions

### 2.1. Componentes

En el estado actual, la arquitectura típica es:

- **Repositorio GitHub**: contiene el código del scraper, el bot de Telegram y la web/panel (por ejemplo, HTML/CSS/JS bajo `docs/` o `/web`).[^5][^6]
- **GitHub Pages**: sirve la web estática del panel desde el propio repo, accesible en una URL tipo `https://usuario.github.io/proyecto`, con datos generados previamente por scripts.[^7]
- **GitHub Actions**: workflows programados con `on: schedule` (cron cada 5 minutos) que:
  - Ejecutan el scraper para recoger cuotas desde casas de apuestas.  
  - Generan ficheros JSON/CSV estáticos que la web lee para mostrar datos.  
  - Opcionalmente invocan el bot de Telegram (por ejemplo, llamando a un script que envía mensajes).[^8][^9]

### 2.2. Limitaciones de este enfoque

Las principales limitaciones son:

- **Duración de jobs**: cada job en un runner de GitHub-hosted puede correr como máximo 6 horas; si se excede, GitHub lo cancela automáticamente.  Esto impide usar Actions como “proceso siempre encendido” para bot o scraper.[^10][^11][^1]
- **Frecuencia mínima de cron**: el evento `schedule` no puede ejecutarse más frecuentemente que cada 5 minutos, y solo desde la rama principal.  Esto limita la capacidad de reaccionar a cambios rápidos de cuotas o de ejecutar scraping muy frecuente.[^3]
- **IP del runner**: los runners de GitHub-hosted tienen IPs asociadas a datacenters (que pueden geolocalizarse fuera de España, por ejemplo en México o EE. UU.), lo que provoca problemas de acceso a webs de casas que restringen tráfico por país.[^4][^3]
- **Uso compartido de recursos**: los runners son recursos compartidos; un scraping intensivo o mal configurado puede chocar con políticas internas y límites de uso (concurrencia, minutos semanales).[^4]

Estas limitaciones explican por qué el scraper falla al intentar acceder a ciertas casas desde GitHub Actions y por qué no es recomendable mantener el bot en long polling allí.

## 3. Papel de la web en GitHub

La web/panel estático en GitHub Pages cumple funciones clave:

- Ofrecer una vista HTML de las surebets detectadas, márgenes, casas implicadas y otros datos, a partir de ficheros generados por el scraper.[^7]
- Permitir visualizar el estado del sistema desde cualquier navegador, sin necesidad de servidor backend complejo (solo un hosting estático).[^7]

Este componente se puede mantener casi igual incluso si se migra el scraper y el bot a otra infraestructura: bastaría con que los datos (JSON/CSV) que la web consume se generen y se sincronizen desde el nuevo host hacia el repositorio de GitHub (por ejemplo, mediante commits automatizados o despliegue de artefactos).[^12][^5]

## 4. Papel del bot de Telegram

El bot de Telegram es el canal de notificación interactivo del sistema:

- Escucha mensajes de usuarios (commands como `/hoy`, `/ahora`, `/stats`) y responde con información sobre surebets, resumen de resultados, etc.[^13][^14]
- Puede funcionar por long polling (conexiones periódicas a la Bot API) o por webhook (recibimiento de peticiones HTTP desde Telegram hacia un servidor propiamente dicho).[^15][^13]

En la arquitectura actual, el bot se afecta por las mismas limitaciones de GitHub Actions: las sesiones de polling no pueden mantenerse 24/7 en un job de Actions y la IP del runner no está bajo control.  Por ello, es preferible ejecutar el bot fuera de Actions (local, VPS, PaaS) y usar GitHub solo como origen del código.[^1][^3]

## 5. Estrategia general de transición manteniendo GitHub y el bot

Para conservar lo que ya existe (repositorio en GitHub, web estática y bot) y mejorar fiabilidad, la estrategia general es:

1. **Mantener GitHub como repositorio de código y lugar de la web estática**.[^6][^7]
2. **Trasladar ejecución continua del scraper y del bot a un entorno con IP adecuada (idealmente española) y sin límites de job de 6 horas**: VPS español, PaaS o máquina local.[^16][^17][^18]
3. **Usar GitHub Actions solo para CI/CD**: testear, construir y desplegar código automáticamente al nuevo host (en lugar de ejecutar el scraping en los runners de Actions).[^8][^1]

Con esto se consigue que GitHub siga centralizando el desarrollo y la web, mientras que la ejecución real se realiza en un entorno controlado.

## 6. Opciones de infraestructura compatibles con esta arquitectura

### 6.1. VPS con IP española

Proveedores de VPS en España como OVHcloud (línea "VPS España"), Hostinet, Raiola Networks y otros ofrecen servidores virtuales con datacenter en España y IP española dedicada.[^17][^19][^18]

Características relevantes:

- Datacenters en España (por ejemplo Madrid), lo que reduce latencia hacia usuarios españoles y hacia sitios en España.[^20][^21]
- IPs españolas que son aceptadas por servicios que restringen acceso geográfico, como algunas casas de apuestas reguladas en España.[^19][^17]
- Planes de coste moderado (habitualmente 3–8 €/mes para 2 vCPU, 2–4 GB RAM y 20–50 GB de almacenamiento), suficientes para scraper, bot y un panel web simple.[^22][^23]

En esta opción, el scraper y el bot se ejecutan continuamente en el VPS, mientras que la web puede seguir en GitHub Pages o migrarse a un virtual host en el VPS.

### 6.2. PaaS (Railway, Fly.io) como entorno de ejecución

Plataformas como Railway y Fly.io permiten desplegar aplicaciones desde repositorios de GitHub y mantener servicios encendidos, incluyendo bots de Telegram, con free tiers y planes económicos.[^24][^25][^26]

Ventajas:

- Integración directa con repositorios de GitHub (deploy automático tras push).[^14][^27]
- Soporte para contenedores de Python/Node que ejecutan bots y APIs de forma continua.[^28][^29]

Limitaciones:

- IP no garantizada como española; puede ser europea o norteamericana según la región. Esto puede seguir planteando problemas con webs que exigen IP España estricta.[^25][^16]

Esta opción es adecuada si el problema de IP no es crítico o si el scraper se ejecuta localmente y sólo el bot y la web se alojan en Railway.

### 6.3. Arquitectura híbrida local + cloud

Una alternativa que combina la IP española residencial con hosting más robusto es:

- **Scraper local**: se ejecuta en el PC del usuario (IP española residencial), accede sin bloqueos a las casas y envía los datos (JSON/CSV) a una API o base de datos en VPS/PaaS.
- **Bot + panel en VPS/PaaS**: se ejecutan en un entorno cloud, leen los datos enviados por el scraper y atienden a usuarios.[^26][^16]

En esta configuración, GitHub sigue siendo el repositorio y lugar de la web estática, mientras que nube y local se reparten las funciones según las restricciones de IP.

## 7. Uso recomendado de GitHub Actions en la nueva arquitectura

GitHub Actions puede seguir siendo útil, pero con otro rol:

- **Tests automáticos**: ejecutar suites de prueba del scraper y del bot en cada push o PR.[^8]
- **Build y empaquetado**: construir imágenes Docker o artefactos para desplegar en el VPS o en Railway.[^30]
- **Deploy automático**: tras un push a `main`, disparar un workflow que conecte con el VPS (por SSH) o con Railway para redeployar la versión actual del código.[^9][^8]

Es importante respetar los límites de GitHub Actions (jobs de hasta 6 horas, workflows de hasta 35 días, cron mínimo cada 5 minutos) y no usarlo como motor de ejecución continua del scraper o del bot.[^3][^10][^1]

## 8. Esquema de documento técnico para tu proyecto

A partir de todo lo anterior, el documento técnico que se puede derivar (la “especificación” de tu proyecto) debería incluir:

- **Descripción de componentes**: scraper, bot, web en GitHub Pages, base de datos y entorno de ejecución.[^5][^7]
- **Diagrama de flujo de datos**: desde casas de apuestas → scraper → almacenamiento → web/bot.[^31][^32]
- **Limitaciones actuales**: IP de GitHub Actions, límites de tiempo, bloqueo de webs.[^1][^3]
- **Plan de transición**: pasos para mover la ejecución continua del scraper/bot a local o a VPS con IP española, manteniendo GitHub como repositorio y host de la web.[^18][^17][^19]
- **Uso futuro de Actions**: tests, CI/CD y despliegue automático, sin depender de runners para scraping.[^9][^8]

Este documento complementa los informes anteriores sobre arbitraje deportivo y arquitectura general, centrándose en tu situación concreta: proyecto ya montado en GitHub Actions con web y bot, y camino para hacerlo robusto y compatible con las restricciones de acceso desde España.

---

## References

1. [Actions limits - GitHub Docs](https://docs.github.com/en/actions/reference/limits) - There are limits in GitHub Actions which you may hit as you scale up, some may be increased by conta...

2. [Timeout for Jobs and Steps - GitHub Actions - KodeKloud Notes](https://notes.kodekloud.com/docs/GitHub-Actions/GitHub-Actions-Core-Concepts/Timeout-for-Jobs-and-Steps/page)

3. [Understanding and overcoming limitations of GitHub Actions - Medium](https://medium.com/@alex.ivenin/understanding-and-overcoming-limitations-of-github-actions-52956e9e2823) - Explore key limitation, practical workarounds and tips for GitHub Actions to maximize CI/CD efficien...

4. [GitHub Actions Policy - Apache Infrastructure Website](https://infra.apache.org/github-actions-policy.html)

5. ["Let's Work on the Next Task": Claude Code, GitHub, and the Most ...](https://www.behind-the-enemy-lines.com/2026/03/lets-work-on-next-task-claude-code.html) - In my previous post , I described how working with AI agents felt like managing an infinitely large,...

6. [GitHub - anthropics/claude-code: Claude Code is an agentic coding ...](https://github.com/anthropics/claude-code) - Claude Code is an agentic coding tool that lives in your terminal, understands your codebase, and he...

7. [How do I take a Claude project public and publish - CometAPI](https://www.cometapi.com/how-do-i-take-a-claude-project-public-and-publish/) - Making a Claude project publicly available usually means two things at once: (1) taking the content ...

8. [Claude Code GitHub Actions - Claude Code Docs](https://code.claude.com/docs/en/github-actions)

9. [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action) - Contribute to anthropics/claude-code-action development by creating an account on GitHub.

10. [Timeout for Jobs and Steps - GitHub Actions](https://notes.kodekloud.com/docs/GitHub-Actions-Certification/GitHub-Actions-Core-Concepts/Timeout-for-Jobs-and-Steps/page)

11. [Github actions job timeout](https://stackoverflow.com/questions/68187987/github-actions-job-timeout) - I have a GitHub workflow with long-running job (10 hours). Even though I have configured the timeout...

12. [Use the GitHub integration | Claude Help Center](https://support.claude.com/en/articles/10167454-use-the-github-integration)

13. [Telegram Bot API Pricing Explained (2026)](https://aziqdev.com/blog/telegram-bot-api-pricing) - The Telegram Bot API is completely free. But hosting, databases, payment providers, and AI APIs add ...

14. [Deploy an AI-Powered Bot for Discord or Telegram](https://docs.railway.com/guides/ai-discord-telegram-bot)

15. [1️⃣ Crear y configurar la VM en Oracle Cloud Free Tier](https://yussel.com.mx/notas/view/index.php?usr=realyussel&nb=Bots&p=Telegram/VM.md&aula=) - Un Script de configuración automática para instalar Python, Git, y tu bot de Telegram en tu VM gratu...

16. [6 Best Telegram Bot Hosting Providers in 2026 (Free & 24/7 ...](https://vpssos.com/6-top-telegram-bot-hosting-providers/) - Compare the best Telegram bot hosting providers in 2026, including 24/7 VPS hosting, free options, R...

17. [VPS Hosting España - Servidores virtuales rápidos y ...](https://www.ovhcloud.com/es-es/vps/vps-espana/) - Descubra el plan de alojamiento VPS de baja latencia en España que mejor se adapte a sus necesidades...

18. [Servidores VPS Cloud rápidos y escalables - Raiola Networks](https://raiolanetworks.com/servidores-vps/) - Servidores VPS en España con virtualización KVM y discos SSD NVME. Potencia y flexibilidad: el combo...

19. [Servidores VPS con Plesk con IP española](https://www.hostinet.com/servidores-vps/) - Servidores VPS en España administrados y no administrados. Con hasta 8 GB de RAM, 100 GB de espacio ...

20. [VPS España | Data centers en España - IONOS](https://www.ionos.es/servidores/vps-espana) - Alojar un servidor VPS en España es una buena forma de usar la nube y llegar a más de 47 millones de...

21. [Top VPS Providers in Spain (2026): Who Actually Has ...](https://www.linkedin.com/pulse/top-vps-providers-spain-2026-who-actually-has-infrastructure-yq5if) - Spain is one of the most strategically positioned server locations in Europe. Madrid sits at the int...

22. [Mejor VPS España - Comparativa 2026 Calidad-Precio](https://www.opiniones.hosting/mejor-vps/) - Estos son los ganadores de las pruebas realizadas para mejor VPS de España. Te mostramos sus caracte...

23. [12 Mejores VPS en España 2026 - Bitcatcha Host Tracker](https://www.bitcatcha.com/es/investigacion/mejor-vps/) - Hostinger es un alojamiento web lituano famoso por sus precios asequibles y su presencia global. Hos...

24. [Railway Free Tier for Telegram Bots: 2026 Limits + Copy- ...](https://starsearn.com/guides/deploy-telegram-bot-railway) - Deploy a Telegram bot on Railway in 2026 with BOT_TOKEN env vars, Python/Node examples, free-tier li...

25. [Where to Host Your Telegram Bot for Free (or Close to It)](https://tgbotforge.com/blog/telegram-bot-hosting-free-options) - Railway, Render, Fly.io, and a $5 VPS - a practical comparison of free and cheap hosting options for...

26. [Best Hosting for Telegram Bots 2026: Run Your Bot Reliably](https://thesoftwarescout.com/best-hosting-for-telegram-bots-2026-run-your-bot-reliably/) - The best hosting for Telegram bots in 2026, ranked for polling and webhook bots, always-on uptime, e...

27. [Bot Templates: Deploy Telegram and WhatsApp Bots 24/7](https://railway.com/deploy/category/bots) - Deploy bot templates on Railway in one click. Run Telegram bots, WhatsApp APIs, and more 24/7 on alw...

28. [Deploy & Host Python Telegram Bot](https://railway.com/deploy/python-telegram-bot) - Deploy and host Python Telegram Bot on Railway in one click — always-on servers, built-in databases,...

29. [Deploy & Host Telegram Bot (Python 3.12)](https://railway.com/deploy/telegram-bot-python-312) - Deploy and host Telegram Bot (Python 3.12) on Railway in one click — always-on servers, built-in dat...

30. [Actions · pi0/telegram-bot-hosting](https://github.com/pi0/telegram-bot-hosting/actions) - A python script to host telegram bots. Contribute to pi0/telegram-bot-hosting development by creatin...

31. [¿Cómo hacer tu propio bot de surebets? Guía completa](https://smartscaner.com/es/articles/mogno_li_sdelat_svoego_bota_dlya_vilok%C2%A0) - ¿Cómo crear un bot para encontrar surebets? En este artículo analizamos los lenguajes de programació...

32. [GitHub - mauricioarauujo/Surebet: Algoritmo que procura por "surebets" em diferentes casas de apostas através de web scrapers.](https://github.com/mauricioarauujo/Surebet) - Algoritmo que procura por "surebets" em diferentes casas de apostas através de web scrapers. - mauri...

