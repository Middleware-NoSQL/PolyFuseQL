from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from sqlglot import exp


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
    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        """Fetch all records for a given entity."""
        pass

    @abstractmethod
    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a JOIN query, either natively
        or via application-side logic."""
        pass

    @abstractmethod
    async def query(
        self, sql: str, params: tuple = None
    ) -> List[dict[str, Any]]:  # noqa: F501
        """Executes a raw SQL-like query."""
        pass

    @abstractmethod
    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a GROUP BY query and returns the aggregated results."""
        pass

    @abstractmethod
    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a simple aggregation query (no GROUP BY)."""
        pass

    @abstractmethod
    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        Bulk inserts data from a file into the specified table.
        Returns the number of records inserted.
        """
        pass
