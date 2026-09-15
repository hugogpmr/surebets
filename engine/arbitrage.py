from .models import Market, SurebetOpportunity


def implied_probability(odds: float) -> float:
    return 1 / odds


def total_implied_probability(market: Market) -> float:
    return sum(implied_probability(o.odds) for o in market.outcomes)


def is_surebet(market: Market, threshold: float = 1.0) -> bool:
    return total_implied_probability(market) < threshold


def margin(market: Market) -> float:
    return 1 - total_implied_probability(market)


def calculate_stakes(market: Market, total_stake: float) -> dict[str, float]:
    total_prob = total_implied_probability(market)
    stakes = {}
    for outcome in market.outcomes:
        key = f"{outcome.bookmaker}:{outcome.name}"
        stakes[key] = round(total_stake * implied_probability(outcome.odds) / total_prob, 2)
    return stakes


def evaluate_market(
    market: Market, total_stake: float, min_margin: float = 0.0
) -> SurebetOpportunity | None:
    m = margin(market)
    if m <= min_margin:
        return None
    stakes = calculate_stakes(market, total_stake)
    profit = round(total_stake * m, 2)
    return SurebetOpportunity(
        market=market,
        margin=m,
        stakes=stakes,
        total_stake=total_stake,
        guaranteed_profit=profit,
    )
