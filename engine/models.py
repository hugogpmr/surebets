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


@dataclass
class MarketComparison:
    """Resultado de comparar cuotas entre casas para un mercado, sea o no
    una surebet. A diferencia de SurebetOpportunity (que solo existe cuando
    hay arbitraje), esto se genera para *todo* mercado comparado, para poder
    mostrar en el panel web tanto las oportunidades reales como el resto.
    """

    market: Market
    margin: float
    is_surebet: bool
    stakes: dict[str, float] | None
    total_stake: float
    guaranteed_profit: float | None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
