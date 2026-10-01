from datetime import datetime, timedelta, timezone

from engine.models import Market, Outcome
from providers.detail_cache import FALLBACK_MAX_AGE, MID_REFRESH, DetailCache, collect, plan
from tests.test_altenar_provider import DETAILS, _event, _FakeProvider

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def market(event="A vs. B"):
    return Market(event=event, sport="futbol", market_type="1X2", outcomes=[Outcome("1", "casa", 2.0)])


def test_near_matches_are_always_reread_and_far_ones_only_when_old():
    cache = DetailCache()
    for key in ("cerca", "medio", "lejos"):
        cache.put(key, [market()], NOW)
    starts = {"cerca": NOW + timedelta(hours=2), "medio": NOW + timedelta(hours=12), "lejos": NOW + timedelta(days=2)}
    assert plan(list(starts), starts.get, cache, NOW + timedelta(minutes=5)) == (["cerca"], ["medio", "lejos"])
    later = NOW + MID_REFRESH
    assert plan(list(starts), starts.get, cache, later) == (["cerca", "medio"], ["lejos"])
    assert cache.due("nueva", NOW + timedelta(days=2), NOW)  # nunca leída: siempre


def test_failed_reread_falls_back_to_a_recent_card_and_drops_unlisted_matches():
    cache = DetailCache()
    cache.put("a", [market("A vs. B")], NOW)
    cache.put("viejo", [market("Ya vs. Empezado")], NOW)
    markets, summary = collect(["a"], ["a"], [None], [], cache, NOW + timedelta(minutes=5))
    assert [m.event for m in markets] == ["A vs. B"] and summary["respaldo"] == 1
    assert len(cache) == 1  # el partido que ya no se lista se olvida
    markets, _ = collect(["a"], ["a"], [None], [], cache, NOW + FALLBACK_MAX_AGE + timedelta(minutes=1))
    assert markets == []  # respaldo demasiado viejo


def test_altenar_rereads_only_due_cards_on_the_second_pass():
    listings = {
        "casa_a": [_event(1, "Cerca vs. Pronto", hours_ahead=2), _event(2, "Lejos vs. Mañana", hours_ahead=40)],
        "casa_b": [_event(1, "Cerca vs. Pronto", hours_ahead=2), _event(2, "Lejos vs. Mañana", hours_ahead=40)],
        "casa_c": [],
    }
    provider = _FakeProvider(listings=listings, details=DETAILS)
    calls = []
    original = provider._get_json

    def counting(client, endpoint, integration, **params):
        if endpoint == "GetEventDetails":
            calls.append(params["eventId"])
        return original(client, endpoint, integration, **params)

    provider._get_json = counting
    first = provider._fetch_football(client=None)
    assert sorted(calls) == [1, 1, 2, 2]
    calls.clear()
    second = provider._fetch_football(client=None)
    assert sorted(calls) == [1, 1]  # el lejano sale de la caché
    assert len(second) == len(first)
