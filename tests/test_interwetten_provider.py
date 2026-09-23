from datetime import datetime, timezone

from providers.interwetten import InterwettenProvider, _parse_start_time

# Forma real de los datos extraídos del DOM de Interwetten (ver _EXTRACT_EVENTS_JS),
# capturada en vivo el 2026-09-22 en la página de La Liga.
RAW_EVENTS = [
    {"teams": ["Málaga", "RCD Espanyol"], "date": "09.10.2026", "time": "21:00", "odds": ["2.65", "3.25", "2.75"]},
    {"teams": ["Solo un equipo"], "date": "09.10.2026", "time": "21:00", "odds": ["1.50"]},
]


def test_parses_1x2_from_raw_dom_events():
    provider = InterwettenProvider()
    markets = provider._parse_events(RAW_EVENTS, "futbol")

    assert len(markets) == 1
    market = markets[0]
    assert market.event == "Málaga vs. RCD Espanyol"
    assert market.market_type == "1X2"
    assert [(o.name, o.odds) for o in market.outcomes] == [("1", 2.65), ("X", 3.25), ("2", 2.75)]
    assert all(o.bookmaker == "interwetten" for o in market.outcomes)


def test_skips_malformed_events():
    markets = InterwettenProvider()._parse_events([{"teams": [], "odds": []}], "futbol")
    assert markets == []


def test_skips_non_numeric_odds():
    events = [{"teams": ["A", "B"], "date": "09.10.2026", "time": "21:00", "odds": ["-", "3.25", "2.75"]}]
    assert InterwettenProvider()._parse_events(events, "futbol") == []


def test_fills_start_time_from_madrid_local_date_and_time():
    # 09.10.2026 21:00 en Madrid (CEST, UTC+2 en octubre) -> 19:00 UTC.
    start = _parse_start_time("09.10.2026", "21:00")
    assert start == datetime(2026, 10, 9, 19, 0, tzinfo=timezone.utc)


def test_start_time_none_when_date_or_time_missing():
    assert _parse_start_time(None, "21:00") is None
    assert _parse_start_time("09.10.2026", None) is None


def test_fast_recheck_is_false_needs_browser():
    assert InterwettenProvider().fast_recheck is False
    assert InterwettenProvider().name == "interwetten"
