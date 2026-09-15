from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Outcome:
    name: str
    bookmaker: str
    odds: float


@dataclass
class Market:
    event: str
    sport: str
    market_type: str
    outcomes: list[Outcome]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SurebetOpportunity:
    market: Market
    margin: float
    stakes: dict[str, float]
    total_stake: float
    guaranteed_profit: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
