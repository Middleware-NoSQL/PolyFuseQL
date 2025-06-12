from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class Connector(ABC):
    def __init__(self, options: Optional[Dict] = None) -> None:
        self._options = options or {}

    @abstractmethod
    async def connect(self):
        """Establish a persistent connection to the database."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Close the persistent connection."""
        pass

    @abstractmethod
    async def ping(self) -> bool:
        pass

    @abstractmethod
    async def count(self, entity: str) -> int:
        pass

    @abstractmethod
    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        pass

    @abstractmethod
    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        pass

    @abstractmethod
    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:  # noqa: F501
        """Update a record by its primary key and
        return the count of updated records."""
        pass

    @abstractmethod
    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        """Delete a record by its primary key and return
        the count of deleted records."""
        pass

    @abstractmethod
    async def query(
        self, sql: str, params: tuple = None
    ) -> List[dict[str, Any]]:  # noqa: F501
        """Executes a raw SQL-like query."""
        pass
