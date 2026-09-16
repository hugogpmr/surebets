from .models import Market, MarketComparison, SurebetOpportunity


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


def format_stakes(stakes: dict[str, float]) -> str:
    """Formatea el reparto de stakes (clave `"casa:resultado"`) en líneas
    legibles para un aviso, p.ej. "   Sportium: 120.50€ a 1".
    """
    lines = []
    for key, amount in stakes.items():
        bookmaker, outcome = key.split(":", 1)
        lines.append(f"   {bookmaker}: {amount}€ a {outcome}")
    return "\n".join(lines)


def compare_market(
    market: Market, total_stake: float, min_margin: float = 0.0
) -> MarketComparison:
    """Igual que evaluate_market, pero siempre devuelve un resultado (nunca
    None): sirve para registrar toda comparación de cuotas, sea o no una
    surebet, de cara al panel web que muestra el estado completo.
    """
    m = margin(market)
    surebet = m > min_margin
    stakes = calculate_stakes(market, total_stake) if surebet else None
    profit = round(total_stake * m, 2) if surebet else None
    return MarketComparison(
        market=market,
        margin=m,
        is_surebet=surebet,
        stakes=stakes,
        total_stake=total_stake,
        guaranteed_profit=profit,
    )


def evaluate_market(
    market: Market, total_stake: float, min_margin: float = 0.0
) -> SurebetOpportunity | None:
    comparison = compare_market(market, total_stake, min_margin)
    if not comparison.is_surebet:
        return None
    return SurebetOpportunity(
        market=market,
        margin=comparison.margin,
        stakes=comparison.stakes,
        total_stake=comparison.total_stake,
        guaranteed_profit=comparison.guaranteed_profit,
    )
