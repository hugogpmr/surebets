from engine.models import Market, Outcome
from providers.base import OddsProvider


class MockProvider(OddsProvider):
    """Datos de ejemplo para probar el motor y el bot sin scrapers reales."""

    name = "mock"

    def fetch_markets(self, sports: list[str]) -> list[Market]:
        return [
            Market(
                event="Real Madrid vs Barcelona",
                sport="futbol",
                market_type="1X2",
                outcomes=[
                    Outcome(name="1", bookmaker="bet365", odds=2.75),
                    Outcome(name="X", bookmaker="codere", odds=3.60),
                    Outcome(name="2", bookmaker="sportium", odds=3.20),
                ],
            ),
            Market(
                event="Djokovic vs Alcaraz",
                sport="tenis",
                market_type="ganador",
                outcomes=[
                    Outcome(name="Djokovic", bookmaker="bet365", odds=2.00),
                    Outcome(name="Alcaraz", bookmaker="sportium", odds=2.05),
                ],
            ),
        ]
