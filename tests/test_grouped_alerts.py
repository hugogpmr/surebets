from datetime import datetime, timedelta, timezone

from engine.models import Market, Outcome
from engine.scan import REALERT_COOLDOWN, normalize_state
from tests.test_scan_cycle import FakeProvider, db, ou, run  # noqa: F401  (db es un fixture)


def btts(yes_book, yes, no_book, no, event="Ajax vs. Feyenoord"):
    return Market(event=event, sport="futbol", market_type="BTTS", outcomes=[Outcome("Yes", yes_book, yes), Outcome("No", no_book, no)])


def providers(over=2.10, extra=True):
    a = [ou("betway", over, 1.80)] + ([btts("betway", 2.2, "betway", 1.6)] if extra else [])
    b = [ou("paf", 1.80, 2.05)] + ([btts("paf", 1.6, "paf", 2.0)] if extra else [])
    return [FakeProvider("altenar", a), FakeProvider("kambi", b)]


def test_surebets_of_the_same_match_go_in_one_message(db):
    sent = run(providers(), db, {}, confirm_cycles=1)
    assert len(sent) == 1
    assert sent[0].startswith("🚨 2 surebets") and sent[0].count("📌") == 2
    assert "Ajax vs. Feyenoord" in sent[0]


def test_already_alerted_is_repeated_only_when_margin_rises_one_point(db):
    state = {}
    assert len(run(providers(extra=False), db, state, confirm_cycles=1)) == 1  # 2.10/2.05: ~3,7 %
    assert run(providers(over=2.12, extra=False), db, state, confirm_cycles=1) == []  # +0,4 puntos
    assert run(providers(over=2.05, extra=False), db, state, confirm_cycles=1) == []  # baja: nunca se repite
    sent = run(providers(over=2.20, extra=False), db, state, confirm_cycles=1)  # +2 puntos sobre lo avisado
    assert len(sent) == 1 and "Surebet mejorada" in sent[0] and "antes" in sent[0]


def test_flickering_surebet_is_not_alerted_again_within_the_cooldown(db):
    state = {}
    assert len(run(providers(extra=False), db, state, confirm_cycles=1)) == 1
    assert run([FakeProvider("altenar", []), FakeProvider("kambi", [])], db, state, confirm_cycles=1) == []
    key = next(iter(state))
    assert state[key]["gone_at"]  # se recuerda
    assert run(providers(extra=False), db, state, confirm_cycles=1) == []  # vuelve: sin aviso
    assert "gone_at" not in state[key]
    # Desaparece más del tiempo de espera: se olvida y, si vuelve, es nueva.
    run([FakeProvider("altenar", []), FakeProvider("kambi", [])], db, state, confirm_cycles=1)
    state[key]["gone_at"] = (datetime.now(timezone.utc) - REALERT_COOLDOWN - timedelta(minutes=1)).isoformat()
    run([FakeProvider("altenar", []), FakeProvider("kambi", [])], db, state, confirm_cycles=1)
    assert key not in state
    assert len(run(providers(extra=False), db, state, confirm_cycles=1)) == 1


def test_state_keeps_the_new_fields():
    raw = {"k": {"margin": 0.02, "cycles": 2, "notified": True, "notified_margin": 0.03, "gone_at": "2026-10-02T10:00:00+00:00"}}
    state = normalize_state(raw)
    assert state["k"]["notified_margin"] == 0.03 and state["k"]["gone_at"].startswith("2026-10-02")
