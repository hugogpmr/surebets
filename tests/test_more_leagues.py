"""Más ligas en Marca Apuestas y Versus (añadidas 2026-09-29): la plataforma "ta-" lee cada
competición con su propia página; la primera (LaLiga) es obligatoria y las demás, no."""

import asyncio

import pytest

import providers.marcaapuestas as marca
import providers.versus as versus
from engine.models import Market, Outcome

CASES = [
    (marca, marca.MarcaApuestasProvider),
    (versus, versus.VersusProvider),
]


class FakePage:
    async def route(self, *args, **kwargs):
        pass


class FakeBrowser:
    async def new_page(self, **kwargs):
        return FakePage()

    async def close(self):
        pass


class FakePlaywright:
    class chromium:
        @staticmethod
        async def launch(**kwargs):
            return FakeBrowser()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _market():
    return Market(event="A vs. B", sport="futbol", market_type="1X2", outcomes=[Outcome("1", "casa", 2.0)])


@pytest.mark.parametrize("module,cls", CASES)
def test_default_extra_leagues_are_soccer_competition_pages_and_custom_urls_get_none(module, cls):
    provider = cls()
    urls = provider.extra_urls["futbol"]
    assert len(urls) == 4 and all("/apuestas/sports/soccer/competitions/" in u and u.endswith("/matches") for u in urls)
    assert len(set(urls)) == len(urls) and provider.competition_urls["futbol"] not in urls
    assert cls(competition_urls={"futbol": "https://x/primary"}).extra_urls == {}


@pytest.mark.parametrize("module,cls", CASES)
def test_a_broken_extra_league_does_not_stop_the_others(monkeypatch, module, cls):
    provider = cls(competition_urls={"futbol": "https://x/primary"}, extra_urls={"futbol": ["https://x/broken", "https://x/ok"]})
    calls = []

    async def fake_competition(self, page, url, sport):
        calls.append(url)
        if url.endswith("broken"):
            raise TimeoutError("sin partidos")
        return [_market()]

    monkeypatch.setattr(module, "async_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(cls, "_fetch_competition", fake_competition)
    markets = asyncio.run(provider._fetch_markets_async(["futbol"]))
    assert len(markets) == 2 and calls == ["https://x/primary", "https://x/broken", "https://x/ok"]


@pytest.mark.parametrize("module,cls", CASES)
def test_a_failing_first_league_aborts_before_reading_the_extras(monkeypatch, module, cls):
    # bloqueo de la casa: no se gasta la espera de cada liga extra
    provider = cls(competition_urls={"futbol": "https://x/primary"}, extra_urls={"futbol": ["https://x/ok"]})
    calls = []

    async def fake_competition(self, page, url, sport):
        calls.append(url)
        raise TimeoutError("bloqueado")

    monkeypatch.setattr(module, "async_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(cls, "_fetch_competition", fake_competition)
    with pytest.raises(TimeoutError):
        asyncio.run(provider._fetch_markets_async(["futbol"]))
    assert calls == ["https://x/primary"]
