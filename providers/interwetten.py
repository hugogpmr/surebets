import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from engine.models import Market, Outcome
from providers.base import OddsProvider

DEFAULT_COMPETITION_URLS = {
    "futbol": "https://www.interwetten.es/es/apuestas-deportivas/l/1030/espana-laliga",
}

# Estructura verificada en vivo el 2026-09-22: lista plana `ul.s-event-group-list`
# que alterna cabeceras de fecha (`li.s-leagueoverview-date-time`, texto
# "DD.MM.AAAA") y partidos (`li.s-event`). Cada partido trae su 1X2 ("Partido")
# ya visible en el listado (sin necesidad de entrar a la ficha), en un único
# `.s-market` con 3 `.s-outcome` (orden 1/X/2 confirmado contra `data-betting`).
# Plataforma propia (no Altenar/Kambi/Sportify): sin API JSON pública
# localizada, así que se lee el DOM ya renderizado, igual que Sportium/Betfair.
# Clases semánticas ("s-event", "s-outcome-odd"...) en vez de CSS-modules con
# hash: más estable que Betfair, pero sigue siendo scraping y puede cambiar.
_EXTRACT_EVENTS_JS = """(container) => {
    const items = Array.from(container.children);
    const events = [];
    let currentDate = null;
    for (const li of items) {
        if (li.classList.contains('s-leagueoverview-date-time')) {
            currentDate = li.textContent.trim();
        } else if (li.classList.contains('s-event')) {
            const teams = Array.from(li.querySelectorAll('.s-event-player')).map(t => t.textContent.trim());
            const timeEl = li.querySelector('.s-event-gametime');
            const odds = Array.from(li.querySelectorAll('.s-market .s-outcome .s-outcome-odd'))
                .map(o => o.textContent.trim());
            events.push({ teams, date: currentDate, time: timeEl ? timeEl.textContent.trim() : null, odds });
        }
    }
    return events;
}"""


class InterwettenProvider(OddsProvider):
    """Scraper por DOM (Playwright) para Interwetten: **bloqueada, no se usa**.

    La estructura del DOM está verificada y el parseo (`_parse_events`) tiene
    test con datos reales, pero `_fetch_markets_async` no funciona: un
    Playwright headless normal (el mismo mecanismo que ya usan Sportium,
    Betfair, CuotasAhora...) recibe el challenge JS de Cloudflare ("Just a
    moment...", con un `__cf_chl_rt_tk` en la URL) en vez de la página real.
    Confirmado en dos entornos distintos el 2026-09-22: este sandbox de
    desarrollo Y el PC de producción del usuario (Windows, IP residencial) -
    no es un problema del sandbox (a diferencia de cuotasahora.com, que sí
    solo afecta al sandbox). El navegador interactivo (Browser pane, no
    headless) sí carga la página sin challenge, pero replicar eso en un
    script automático para esquivarlo sería evasión de anti-bot, que este
    proyecto no hace (mismo criterio que Kirolbet/Betsson/Suertia). Se
    conserva el código, sin usar, por si Interwetten cambia de protección
    más adelante.
    """

    name = "interwetten"
    fast_recheck = False  # necesita navegador, igual que Sportium/Betfair

    def __init__(self, competition_urls: dict[str, str] | None = None):
        self.competition_urls = competition_urls or DEFAULT_COMPETITION_URLS

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return asyncio.run(self._fetch_markets_async(sports))

    async def _fetch_markets_async(self, sports: list[str]) -> list[Market]:
        markets: list[Market] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for sport in sports:
                url = self.competition_urls.get(sport)
                if not url:
                    continue
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_selector(".s-event-group-list", timeout=20000)
                raw_events = await page.eval_on_selector(".s-event-group-list", _EXTRACT_EVENTS_JS)
                markets.extend(self._parse_events(raw_events, sport))
            await browser.close()
        return markets

    def _parse_events(self, raw_events: list[dict], sport: str) -> list[Market]:
        markets = []
        for event in raw_events:
            teams = event.get("teams", [])
            odds = event.get("odds", [])
            if len(teams) != 2 or len(odds) != 3:
                continue
            try:
                outcomes = [
                    Outcome(name="1", bookmaker=self.name, odds=float(odds[0])),
                    Outcome(name="X", bookmaker=self.name, odds=float(odds[1])),
                    Outcome(name="2", bookmaker=self.name, odds=float(odds[2])),
                ]
            except ValueError:
                continue
            event_name = f"{teams[0]} vs. {teams[1]}"
            market = Market(event=event_name, sport=sport, market_type="1X2", outcomes=outcomes)
            market.start_time = _parse_start_time(event.get("date"), event.get("time"))
            markets.append(market)
        return markets


def _parse_start_time(date_str: str | None, time_str: str | None) -> datetime | None:
    """"DD.MM.AAAA" + "HH:MM", ambos en hora de Madrid (la que muestra la web
    para usuarios en España), a UTC. None si falta alguno de los dos o si el
    sistema no tiene base de datos de zonas horarias (Windows sin `tzdata`:
    mismo problema documentado en engine/labels.py)."""
    if not date_str or not time_str:
        return None
    try:
        from zoneinfo import ZoneInfo

        day, month, year = (int(p) for p in date_str.split("."))
        hour, minute = (int(p) for p in time_str.split(":"))
        local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Madrid"))
        return local.astimezone(timezone.utc)
    except Exception:
        return None
