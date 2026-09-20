from abc import ABC, abstractmethod

from engine.models import Market


class OddsProvider(ABC):
    name: str
    # True si el proveedor es una API directa y barata (sin navegador), que
    # engine.scan puede volver a leer en el mismo escaneo para verificar una
    # surebet de margen muy alto (ver engine/quality.py).
    fast_recheck: bool = False

    @abstractmethod
    def fetch_markets(self, sports: list[str]) -> list[Market]:
        ...
