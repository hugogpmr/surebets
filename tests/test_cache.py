import asyncio
import itertools
import logging
from datetime import datetime, timedelta, timezone

import pytest

from engine.cache import CachedProvider, ComparatorCache, refresh_cache, supported_keys
from engine.models import Market, Outcome
from engine.scan import run_scan_cycle
from providers.base import OddsProvider
from storage.db import export_snapshot, init_db

LOGGER = logging.getLogger("test")
NOW = datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc)


def market(event="Ajax vs. Feyenoord", mt="OU_2.5", over=("bet365", 2.1), under=("bwin", 2.05), start=None, source="", at=None):
    return Market(
        event=event,
        sport="futbol",
        market_type=mt,
        outcomes=[
            Outcome("Over", over[0], over[1], source=source, fetched_at=at),
            Outcome("Under", under[0], under[1], source=source, fetched_at=at),
        ],
        start_time=start,
        fetched_at=at or NOW,
    )


class FakeComparator(OddsProvider):
    def __init__(self, name, results, league_urls):
        self.name = name
        self.league_urls = league_urls
        self._results = results  # clave -> lista de mercados (o excepción)
        self.calls = []

    def fetch_markets(self, sports):
        self.calls.append(list(sports))
        result = self._results[sports[0]]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def cache(tmp_path):
    return ComparatorCache(str(tmp_path / "cache" / "c.json"))


def test_round_trip_keeps_odds_source_times_and_kickoff(cache):
    start = NOW + timedelta(hours=5)
    original = market(start=start, source="cuotasahora", at=NOW - timedelta(minutes=7))
    cache.update("cuotasahora", "futbol", [original], NOW)
    markets, summary = cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=8), NOW + timedelta(minutes=30))
    (loaded,) = markets
    assert loaded.event == original.event and loaded.market_type == "OU_2.5" and loaded.start_time == start
    assert [(o.name, o.bookmaker, o.odds, o.source) for o in loaded.outcomes] == [
        ("Over", "bet365", 2.1, "cuotasahora"),
        ("Under", "bwin", 2.05, "cuotasahora"),
    ]
    # la edad ORIGINAL de la cuota se conserva: el motor puede ver que es vieja
    assert loaded.outcomes[0].fetched_at == NOW - timedelta(minutes=7)
    assert summary == {"leagues": 1, "markets": 1, "oldest_minutes": 30, "newest_minutes": 30}


def test_missing_file_and_unrequested_leagues_give_nothing(cache):
    assert cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=1), NOW)[0] == []
    cache.update("cuotasahora", "futbol_premier", [market()], NOW)
    assert cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=1), NOW)[0] == []


def test_entries_older_than_max_age_are_not_served(cache):
    cache.update("cuotasahora", "futbol", [market()], NOW - timedelta(hours=9))
    assert cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=8), NOW)[0] == []
    assert len(cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=10), NOW)[0]) == 1


def test_an_empty_read_does_not_wipe_previous_data(cache):
    cache.update("cuotasahora", "futbol", [market()], NOW - timedelta(hours=1))
    assert cache.update("cuotasahora", "futbol", [], NOW) is False
    markets, summary = cache.markets_for("cuotasahora", ["futbol"], timedelta(hours=8), NOW)
    assert len(markets) == 1 and summary["oldest_minutes"] == 60  # sigue siendo la lectura antigua
    # pero un primer intento vacío sí se anota (para rotar)
    assert cache.update("cuotasahora", "futbol_premier", [], NOW) is True


def test_stalest_first_puts_never_read_first_then_oldest_attempt(cache):
    cache.update("cuotasahora", "a", [market()], NOW - timedelta(hours=3))
    cache.update("cuotasahora", "b", [market()], NOW - timedelta(hours=1))
    order = cache.stalest_first([("cuotasahora", "b"), ("cuotasahora", "a"), ("cuotasahora", "nueva")])
    assert [key for _, key in order] == ["nueva", "a", "b"]


def test_refresh_cache_rotates_within_the_time_budget(cache):
    urls = {"a": "u", "b": "u", "c": "u"}
    provider = FakeComparator("cuotasahora", {k: [market(event=f"{k} vs. z")] for k in urls}, urls)
    ticks = iter(range(0, 1000, 10))  # cada llamada al reloj avanza 10 s
    done = refresh_cache([provider], ["a", "b", "c"], cache, timedelta(seconds=25), LOGGER, clock=lambda: next(ticks))
    assert 0 < len(done) < 3  # el presupuesto se agota antes de leerlas todas
    first_round = {call[0] for call in provider.calls}
    refresh_cache([provider], ["a", "b", "c"], cache, timedelta(seconds=25), LOGGER, clock=lambda: next(ticks))
    second_round = {call[0] for call in provider.calls} - first_round
    # la siguiente ronda continúa por competiciones que aún no se habían leído, no repite
    assert second_round and not (second_round & first_round)


def test_refresh_cache_survives_a_failing_league_and_stamps_source(cache):
    urls = {"a": "u", "b": "u"}
    provider = FakeComparator("cuotasahora", {"a": RuntimeError("boom"), "b": [market()]}, urls)
    done = refresh_cache([provider], ["a", "b"], cache, timedelta(hours=1), LOGGER)
    assert done == {("cuotasahora", "a"): 0, ("cuotasahora", "b"): 1}
    (loaded,) = cache.markets_for("cuotasahora", ["b"], timedelta(hours=1))[0]
    assert {o.source for o in loaded.outcomes} == {"cuotasahora"} and loaded.outcomes[0].fetched_at is not None


def test_only_competitions_a_provider_supports_are_read(cache):
    only_futbol = FakeComparator("betexplorer", {"futbol": [market()]}, {"futbol": "u"})
    refresh_cache([only_futbol], ["futbol", "baloncesto_nba"], cache, timedelta(hours=1), LOGGER)
    assert only_futbol.calls == [["futbol"]]
    assert supported_keys(only_futbol) == ["futbol"]


class FakeDynamicComparator(OddsProvider):
    """Como CasasDeApuestasProvider: descubre sus competiciones solo, sin `league_urls`
    - ofrece unidades de caché por competición vía `cache_units`. `competitions` es
    {deporte base: [rutas de competición]}; cada unidad devuelve un mercado propio
    (`mt` = la ruta, para distinguirlos en las aserciones)."""

    def __init__(self, name, competitions):
        self.name = name
        self._competitions = competitions
        self.fetch_calls = []  # (deporte, ruta) de cada unidad realmente invocada

    def fetch_markets(self, sports):  # modos full/fast en vivo: no lo ejercitan estos tests
        raise NotImplementedError

    def cache_units(self, sports):
        requested = {key.split("_", 1)[0] for key in sports} & set(self._competitions)
        units = []
        for sport in sorted(requested):
            for comp_path in self._competitions[sport]:
                units.append((f"{sport}::{comp_path}", self._fetcher(sport, comp_path)))
        return units

    def _fetcher(self, sport, comp_path):
        def fetch():
            self.fetch_calls.append((sport, comp_path))
            return [market(mt=comp_path)]

        return fetch


def test_dynamic_provider_gets_one_cache_unit_per_competition(cache):
    # baloncesto tiene varias claves compuestas en la lista global (acb/nba); un
    # provider que descubre solo debe recibir una unidad por CADA competición real
    # que descubra, no una sola por deporte ni una redundante por clave compuesta -
    # así el presupuesto del ciclo lento se reparte en trozos pequeños, como con
    # CuotasAhora (ver docstring de cache_units en providers/casasdeapuestas.py).
    provider = FakeDynamicComparator(
        "casasdeapuestas", {"futbol": ["/liga1", "/liga2"], "baloncesto": ["/acb"]}
    )
    sports = ["baloncesto_acb", "baloncesto_nba", "futbol_champions", "tenis_atp"]
    refresh_cache([provider], sports, cache, timedelta(hours=1), LOGGER)
    # tenis no está entre las competiciones del provider: fuera. 3 unidades reales
    # (2 fútbol + 1 baloncesto), cada una leída una sola vez.
    assert sorted(provider.fetch_calls) == [("baloncesto", "/acb"), ("futbol", "/liga1"), ("futbol", "/liga2")]


def test_dynamic_provider_cache_round_trips_through_slow_and_fast_cycles(cache):
    provider = FakeDynamicComparator("casasdeapuestas", {"baloncesto": ["/acb", "/nba"]})
    sports = ["baloncesto_acb", "baloncesto_nba"]

    refresh_cache([provider], sports, cache, timedelta(hours=1), LOGGER)
    assert len(provider.fetch_calls) == 2  # una llamada por competición, no una por clave compuesta

    # El ciclo rápido pide con la lista COMPLETA de claves compuestas (como hace
    # engine/scan.py de verdad): debe encontrar lo guardado bajo las dos claves
    # dinámicas ("baloncesto::/acb", "baloncesto::/nba") igualmente, aunque ninguna
    # coincida por texto exacto con "baloncesto_acb"/"baloncesto_nba".
    cached_provider = CachedProvider("casasdeapuestas", cache, timedelta(hours=1))
    markets = cached_provider.fetch_markets(sports)
    assert {m.market_type for m in markets} == {"/acb", "/nba"}


def test_dynamic_provider_only_budgets_one_competition_at_a_time(cache):
    # El motivo real de todo esto: un ciclo lento con presupuesto para UNA sola unidad
    # no debe intentar leer un deporte entero de golpe (eso es justo lo que se rompió
    # antes de este fix) - debe parar tras la primera competición y dejar el resto
    # para la siguiente pasada, igual que ya hacía con CuotasAhora.
    provider = FakeDynamicComparator("casasdeapuestas", {"futbol": ["/liga1", "/liga2", "/liga3"]})
    ticks = iter(itertools.count(start=0.0, step=0.5))  # agota el presupuesto tras la primera unidad
    refresh_cache([provider], ["futbol"], cache, timedelta(seconds=1), LOGGER, clock=lambda: next(ticks))
    assert len(provider.fetch_calls) == 1


# --- ciclo rápido: caché + directas en un mismo escaneo ------------------------------------------------------------


class FakeDirect(OddsProvider):
    fast_recheck = False

    def __init__(self, name, markets):
        self.name, self._m = name, markets

    def fetch_markets(self, sports):
        return self._m


def run_fast(providers, db):
    sent = []

    async def notify(text):
        sent.append(text)

    result = asyncio.run(
        run_scan_cycle(providers, ["futbol"], 250.0, 0.01, db, {}, notify=notify, logger=LOGGER, confirm_cycles=1)
    )
    return sent, result


def test_fast_cycle_combines_cached_comparator_with_fresh_direct_data(cache, tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    # comparador leído hace 3 h (de la caché): bet365 paga Over 2.30
    cache.update("cuotasahora", "futbol", [market(over=("bet365", 2.30), under=("bwin", 1.60), source="cuotasahora", at=datetime.now(timezone.utc) - timedelta(hours=3))])
    cached = CachedProvider("cuotasahora", cache, timedelta(hours=8))
    # directa recién leída: paf paga Under 2.10
    direct = FakeDirect("kambi", [market(over=("paf", 1.60), under=("paf", 2.10))])
    sent, result = run_fast([cached, direct], db)

    assert len(sent) == 1 and "bet365←cuotasahora" in sent[0] and "paf←kambi" in sent[0]
    # la cuota de la caché conserva su antigüedad real: el motor la marca como desfasada
    assert "las cuotas se leyeron con mucha diferencia de tiempo" in sent[0]
    assert result["sources"]["cuotasahora"]["markets"] == 1 and result["sources"]["kambi"]["ok"]
    row = export_snapshot(db)["comparisons"][0]
    assert row["reliability"] == "baja" and "cuotas_desfasadas" in row["flags"]


def test_fast_cycle_with_an_empty_cache_still_works_with_direct_sources_only(cache, tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    cached = CachedProvider("cuotasahora", cache, timedelta(hours=8))
    direct = FakeDirect("kambi", [market(over=("paf", 2.2), under=("leovegas", 2.1))])
    sent, result = run_fast([cached, direct], db)
    assert len(sent) == 1
    assert result["sources"]["cuotasahora"]["markets"] == 0  # visible: la caché está vacía
    assert cached.summary["leagues"] == 0


def test_first_round_follows_the_priority_order_and_interleaves_providers(cache):
    pairs = [
        ("cuotasahora", "futbol"),
        ("cuotasahora", "futbol_premier"),
        ("cuotasahora", "baloncesto_nba"),
        ("betexplorer", "futbol"),
    ]
    assert cache.stalest_first(pairs) == [
        ("betexplorer", "futbol"),
        ("cuotasahora", "futbol"),
        ("cuotasahora", "futbol_premier"),
        ("cuotasahora", "baloncesto_nba"),
    ]


# --- prioridad de la rotación y reintento de lecturas vacías -----------------------------------------------------


def test_top_leagues_are_due_sooner_than_low_priority_ones(cache):
    keys = ["futbol", "futbol_champions", "futbol_premier", "futbol_seriea", "futbol_bundesliga", "futbol_ligue1",
            "futbol_suecia", "baloncesto_nba"]
    now = datetime.now(timezone.utc)
    # todas leídas hace 3 h: LaLiga (intervalo 2 h) ya toca; Suecia (5 h) y NBA (8 h) todavía no
    for key in keys:
        cache.update("cuotasahora", key, [market()], now - timedelta(hours=3))
    order = [key for _, key in cache.stalest_first([("cuotasahora", k) for k in keys])]
    assert order[:6] == keys[:6] and order[-2:] == ["futbol_suecia", "baloncesto_nba"]


def test_a_low_priority_league_read_long_ago_beats_a_fresh_top_league(cache):
    now = datetime.now(timezone.utc)
    keys = ["futbol", "futbol_champions", "futbol_premier", "futbol_seriea", "futbol_bundesliga", "futbol_ligue1", "futbol_suecia"]
    for key in keys[:6]:
        cache.update("cuotasahora", key, [market()], now - timedelta(minutes=10))
    cache.update("cuotasahora", "futbol_suecia", [market()], now - timedelta(hours=7))
    order = cache.stalest_first([("cuotasahora", k) for k in keys])
    assert order[0] == ("cuotasahora", "futbol_suecia")


def test_empty_reads_are_retried_soon_with_growing_delay(cache):
    now = datetime.now(timezone.utc)
    keys = ["futbol", "futbol_champions", "futbol_premier", "futbol_seriea", "futbol_bundesliga", "futbol_ligue1"]
    for key in keys:
        cache.update("cuotasahora", key, [market()], now - timedelta(minutes=45))
    cache.update("cuotasahora", "futbol_ligue1", [], now - timedelta(minutes=45))  # 1ª lectura vacía: reintento a los 20 min
    order = [k for _, k in cache.stalest_first([("cuotasahora", k) for k in keys])]
    assert order[0] == "futbol_ligue1"  # ya vencido; las demás no vencen hasta las 2 h


def test_retry_delay_doubles_and_never_exceeds_the_normal_interval():
    from engine.cache import OTHER_INTERVAL, TOP_INTERVAL, retry_delay

    assert [retry_delay(n, OTHER_INTERVAL) for n in (1, 2, 3, 4, 10)] == [
        timedelta(minutes=20), timedelta(minutes=40), timedelta(minutes=80), OTHER_INTERVAL, OTHER_INTERVAL
    ]
    assert retry_delay(3, TOP_INTERVAL) == TOP_INTERVAL


def test_retry_delay_does_not_overflow_with_a_very_long_empty_streak():
    # Una competición fuera de temporada acumula una lectura vacía por ciclo lento: con
    # ~43 seguidas `2 ** n` desbordaba el timedelta y el ciclo lento moría (VM, 2026-09-28).
    from engine.cache import FOOTBALL_INTERVAL, OTHER_INTERVAL, TOP_INTERVAL, retry_delay

    for streak in (43, 60, 10_000):
        for interval in (TOP_INTERVAL, FOOTBALL_INTERVAL, OTHER_INTERVAL):
            assert retry_delay(streak, interval) == interval


def test_a_good_read_resets_the_empty_streak(cache):
    now = datetime.now(timezone.utc)
    cache.update("cuotasahora", "futbol", [], now)
    cache.update("cuotasahora", "futbol", [], now)
    assert cache._read()["entries"]["cuotasahora|futbol"]["empty_streak"] == 2
    cache.update("cuotasahora", "futbol", [market()], now)
    assert cache._read()["entries"]["cuotasahora|futbol"]["empty_streak"] == 0
