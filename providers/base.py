from abc import ABC, abstractmethod

from engine.models import Market


class OddsProvider(ABC):
    name: str

    @abstractmethod
    def fetch_markets(self, sports: list[str]) -> list[Market]:
        ...
