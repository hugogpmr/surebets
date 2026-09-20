from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Outcome:
    name: str
    bookmaker: str
    odds: float
    # De qué proveedor salió esta cuota ("altenar", "cuotasahora"...) y cuándo
    # se leyó. Los rellena engine.scan justo tras el fetch, los providers no
    # tienen que ocuparse. Sirven para distinguir cuotas directas de la casa de
    # las de un comparador (que pueden ir desfasadas): ver engine/quality.py.
    source: str = ""
    fetched_at: datetime | None = None


@dataclass
class Market:
    event: str
    sport: str
    market_type: str
    outcomes: list[Outcome]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Hora de inicio del partido (UTC) cuando el proveedor la conoce (hoy:
    # Altenar y Kambi); None = desconocida. Sirve para no cruzar partidos
    # distintos entre casas y para desconfiar de comparadores cerca del inicio.
    start_time: datetime | None = None


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
    # Avisos de calidad (ver engine/quality.py) y fiabilidad global ("alta",
    # "media" o "baja"; "" si aún no se ha evaluado).
    flags: list[str] = field(default_factory=list)
    reliability: str = ""
    # Reparto con importes "naturales" (múltiplos de 5 € por defecto) que sigue
    # garantizando beneficio; None si no existe uno válido.
    rounded_stakes: dict[str, float] | None = None
    rounded_profit: float | None = None
