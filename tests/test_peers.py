import json
from datetime import datetime, timedelta, timezone

from engine.models import Market, Outcome
from engine.peers import MAX_AGE, MIN_EVENTS, PeerEvents

NOW = datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc)


def markets(n, books=("paf", "Leovegas"), sport="futbol"):
    return [
        Market(event=f"Local{i} vs. Visitante{i}", sport=sport, market_type="1X2",
               outcomes=[Outcome("1", b, 2.0) for b in books])
        for i in range(n)
    ]


def test_roundtrip_keeps_events_sports_and_lowercased_bookmakers(tmp_path):
    store = PeerEvents(str(tmp_path / "cache" / "p.json"))  # la carpeta no existe aún
    store.save(markets(MIN_EVENTS) + markets(3, sport="tenis"), NOW)
    loaded = store.load(NOW + timedelta(minutes=12))
    assert len(loaded) == MIN_EVENTS + 3
    assert {m.sport for m in loaded} == {"futbol", "tenis"}
    assert {o.bookmaker for m in loaded for o in m.outcomes} == {"paf", "leovegas"}


def test_same_event_from_several_markets_is_stored_once_with_all_bookmakers(tmp_path):
    store = PeerEvents(str(tmp_path / "p.json"))
    many = markets(MIN_EVENTS)
    many += [Market(event=many[0].event, sport="futbol", market_type="OU_2.5", outcomes=[Outcome("Over", "bet777", 1.9)])]
    store.save(many, NOW)
    loaded = {m.event: sorted(o.bookmaker for o in m.outcomes) for m in store.load(NOW)}
    assert len(loaded) == MIN_EVENTS and loaded[many[0].event] == ["bet777", "leovegas", "paf"]


def test_too_old_or_too_poor_or_missing_or_corrupt_data_is_ignored(tmp_path):
    path = tmp_path / "p.json"
    store = PeerEvents(str(path))
    assert store.load(NOW) is None  # no existe
    store.save(markets(MIN_EVENTS), NOW)
    assert store.load(NOW + MAX_AGE - timedelta(minutes=1)) is not None
    assert store.load(NOW + MAX_AGE + timedelta(minutes=1)) is None  # demasiado viejo
    store.save(markets(MIN_EVENTS - 1), NOW)
    assert store.load(NOW) is None  # ciclo anterior cojo: mejor esperar a datos frescos
    path.write_text("{no es json", encoding="utf-8")
    assert store.load(NOW) is None
    path.write_text(json.dumps({"saved_at": "ayer", "events": {}}), encoding="utf-8")
    assert store.load(NOW) is None


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    store = PeerEvents(str(tmp_path / "p.json"))
    store.save(markets(MIN_EVENTS), NOW)
    assert [f.name for f in tmp_path.iterdir()] == ["p.json"]
