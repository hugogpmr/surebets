from abc import ABC, abstractmethod

from engine.models import Market


class OddsProvider(ABC):
    name: str
    # True si el proveedor es una API directa y barata (sin navegador), que
    # engine.scan puede volver a leer en el mismo escaneo para verificar una
    # surebet de margen muy alto (ver engine/quality.py).
    fast_recheck: bool = False
    # True si la lectura lanza un Chromium entero (Playwright). Solo estos pasan por el
    # semáforo `max_concurrency` del escaneo: son los que saturan la CPU si arrancan todos a
    # la vez. Las fuentes por httpx (Altenar, Kambi, Bet777...) son E/S pura y arrancan al
    # instante, sin cola detrás de un navegador.
    uses_browser: bool = False
    # True si el proveedor tiene una SEGUNDA pasada (`refine`) que se ejecuta cuando ya
    # se han leído todas las fuentes: sirve para gastar el trabajo caro (una página de
    # navegador por partido) solo en los partidos que otra casa también lista, que son
    # los únicos que pueden dar una surebet. Ver engine/scan.py:_refine.
    refines: bool = False
    # True si conviene "aparcar" el proveedor cuando falla o viene vacío ciclo tras ciclo
    # (engine/health.py): solo para los que lanzan un navegador entero, donde un bloqueo
    # permanente (p.ej. la IP de un datacenter) cuesta CPU y RAM cada vez para no sacar nada.
    parkable: bool = False

    @abstractmethod
    def fetch_markets(self, sports: list[str]) -> list[Market]:
        ...

    def refine(self, sports: list[str], peer_markets: list[Market]) -> list[Market]:
        """Mercados extra de la segunda pasada. `peer_markets` son los de las DEMÁS
        fuentes, ya leídos. Solo se llama si `refines` es True."""
        return []
