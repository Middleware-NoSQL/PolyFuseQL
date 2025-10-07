import asyncio
import csv
from typing import Any, Dict, List, Optional

import aiohttp
from cassandra.cluster import Cluster, Session
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import BatchStatement
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector import Connector
from polyfuseql.config import AppSettings
import logging

logger = logging.getLogger(__name__)


class CassandraConnector(Connector):
    """
    Connector for Cassandra, implementing the full Connector interface.
    Uses an external service for ALL SQL-to-CQL query translations.
    """

    def __init__(
        self,
        settings: AppSettings,
        options: Optional[Dict] = None,
        catalogue: Optional[Catalogue] = None,
        is_local_implementation: bool = False,
    ):
        super().__init__(options, catalogue, is_local_implementation)
        self.settings = settings.cassandra
        self.translator_url = settings.cassandra_translator_url
        self._cluster: Cluster | None = None
        self._session: Session | None = None
        self._http_session = aiohttp.ClientSession()
        logger.info(
            f"CassandraConnector initialized for keyspace: {self.settings.keyspace}"  # noqa:E501
        )

    async def _run_in_executor(self, func, *args):
        """Runs a blocking function in a separate thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    async def connect(self):
        """Establishes a connection to the Cassandra cluster."""
        if self._cluster:
            return
        try:
            auth_provider = None
            if self.settings.user and self.settings.password:
                auth_provider = PlainTextAuthProvider(
                    username=self.settings.user,
                    password=self.settings.password,  # noqa:E501
                )
            self._cluster = await self._run_in_executor(
                Cluster,
                [self.settings.host],
                port=self.settings.port,
                auth_provider=auth_provider,
            )
            self._session = await self._run_in_executor(
                self._cluster.connect, self.settings.keyspace
            )
            await self.ping()
            logger.info("Successfully connected to Cassandra.")
        except Exception as e:
            logger.error(f"Failed to connect to Cassandra: {e}")
            self._cluster = None
            self._session = None
            raise

    async def disconnect(self):
        """Closes the connection to the Cassandra cluster."""
        if self._cluster:
            await self._run_in_executor(self._cluster.shutdown)
            self._cluster = None
            self._session = None
            logger.info("Cassandra connection closed.")
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def ping(self) -> bool:
        """Pings the Cassandra cluster to check the connection."""
        if not self._session:
            raise ConnectionError("Not connected to Cassandra.")
        try:
            result = await self._run_in_executor(
                self._session.execute,
                "SELECT release_version FROM system.local;",
                timeout=5,
            )
            return bool(result.one())
        except Exception as e:
            logger.error(f"Cassandra ping failed: {e}")
            return False

    def _format_value(self, value: Any) -> str:
        """Formats a Python value into a SQL literal."""
        if isinstance(value, str):
            # FIX: Rewritten using triple-quoted f-string to robustly handle
            # nested quotes and prevent syntax errors.
            return f"""'{value.replace("'", "''")}'"""
        if value is None:
            return "NULL"
        return str(value)

    async def _translate_sql_to_cql(self, sql_query: str) -> str:
        """Sends SQL to the translation service and returns the CQL query."""
        url = f"{self.translator_url}/api/translator/translate"
        payload = {"sql": sql_query}
        try:
            async with self._http_session.post(url, json=payload) as response:
                response.raise_for_status()
                translation = await response.json()
                if not translation:
                    return ""
                if "cql" not in translation:
                    raise ValueError(
                        "Invalid response from translator: 'cql' key missing."
                    )
                return translation["cql"]
        except aiohttp.ClientError as e:
            logger.error(f"Error calling translation service: {e}")
            raise ConnectionError(
                f"Failed to communicate with translator: {e}"
            )  # noqa:E501

    async def query(
        self, sql: str, params: tuple = None
    ) -> List[Dict[str, Any]]:  # noqa:E501
        """Translates a SQL query to CQL and executes it."""
        await self.connect()
        cql_query = await self._translate_sql_to_cql(sql)

        if not cql_query:
            return []

        result = await self._run_in_executor(self._session.execute, cql_query)
        return [dict(row) for row in result]

    async def count(self, entity: str) -> int:
        """Counts rows by generating a 'SELECT COUNT' query."""
        sql = f"SELECT COUNT(*) FROM {entity}"
        result = await self.query(sql)
        if result and result[0]:
            return next(iter(result[0].values()), 0)
        return 0

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any] | None:  # noqa:E501
        """Fetches a row by generating a 'SELECT' query with a WHERE clause."""
        pk_val_formatted = self._format_value(pk_val)
        sql = f"SELECT * FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        result = await self.query(sql)
        return result[0] if result else None

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        """Fetches all rows by generating a 'SELECT *' query."""
        sql = f"SELECT * FROM {entity}"
        return await self.query(sql)

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        """Inserts a row by generating an 'INSERT' query."""
        cols = ", ".join(payload.keys())
        vals = ", ".join(self._format_value(v) for v in payload.values())
        sql = f"INSERT INTO {entity} ({cols}) VALUES ({vals})"
        await self.query(sql)
        return True

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        """Updates a row by generating an 'UPDATE' query."""
        set_clause = ", ".join(
            f"{k} = {self._format_value(v)}" for k, v in payload.items()
        )
        pk_val_formatted = self._format_value(pk_val)
        sql = f"UPDATE {entity} SET {set_clause} WHERE {pk_col} = {pk_val_formatted}"  # noqa:E501
        await self.query(sql)
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        """Deletes a row by generating a 'DELETE' query."""
        pk_val_formatted = self._format_value(pk_val)
        sql = f"DELETE FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        await self.query(sql)
        return 1

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a JOIN query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a GROUP BY query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes an aggregation query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        Bulk inserts data from a CSV file directly using the driver.
        NOTE: This method bypasses the translator for performance reasons.
        """
        await self.connect()
        try:
            with open(file_path, "r", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                placeholders = ", ".join(["?"] * len(header))
                cql = f"INSERT INTO {table_name} ({', '.join(header)}) VALUES ({placeholders})"  # noqa:E501

                prepared_statement = await self._run_in_executor(
                    self._session.prepare, cql
                )
                batch = BatchStatement()
                count = 0
                for row in reader:
                    batch.add(prepared_statement, row)
                    count += 1
                    if count % 100 == 0:
                        await self._run_in_executor(
                            self._session.execute, batch
                        )  # noqa:E501
                        batch.clear()
                if batch:
                    await self._run_in_executor(self._session.execute, batch)
                return count
        except FileNotFoundError:
            logger.error(f"Bulk insert file not found: {file_path}")
            return 0
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            raise
