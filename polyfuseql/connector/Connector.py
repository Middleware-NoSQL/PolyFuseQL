# connector_base.py
from abc import ABC, abstractmethod
from typing import Dict, Any


class Connector(ABC):
    def __init__(self, options: Dict = None) -> None:
        self._options = options or {}

    @abstractmethod
    async def ping(self) -> bool:
        pass

    @abstractmethod
    async def count(self, entity: str) -> int:
        pass

    @abstractmethod
    async def get(self, entity: str, pk: str) -> Dict[str, Any]:
        pass
