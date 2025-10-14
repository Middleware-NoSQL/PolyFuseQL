import logging
from typing import Any, Dict, List, Optional

import aiohttp
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import AppSettings
from polyfuseql.connector import Connector

logger = logging.getLogger(__name__)


class CassandraConnector(Connector):
    """
    Connector for Cassandra that relies on an external
    translation microservice. All operations are sent as SQL strings to
    the translator API.
    """

    def __init__(
        self,
        settings: AppSettings,
        options: Optional[Dict] = None,
        catalogue: Optional[Catalogue] = None,
        is_local_implementation: bool = False,
    ):
        # Set is_local_implementation to False
        super().__init__(options, catalogue, is_local_implementation)
        self.settings = settings.cassandra
        self.auth_settings = settings.cassandra.auth
        self.translator_url = settings.cassandra_translator_url
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._translator_auth_token: Optional[str] = None
        logger.info(
            f"CassandraConnector initialized for translator at {self.translator_url}"  # noqa:E501
        )

    async def ping(self) -> bool:
        """Pings the translator service's health check endpoint."""
        if not self._http_session:
            raise ConnectionError(
                "Cannot ping, session not connected. Call connect() first."
            )

        # The health endpoint is likely at the root or a dedicated /health path
        # Using the base URL as a simple connectivity check.
        health_url = self.translator_url.rsplit("/api", 1)[0] + "/api"
        try:
            async with self._http_session.get(
                health_url, timeout=5
            ) as response:  # noqa:E501
                return (
                    response.status < 500
                )  # Consider any non-server error as a success
        except Exception as e:
            logger.error(f"Failed to ping Cassandra translator service: {e}")
            return False

    async def _authenticate_with_translator(self):
        """
        Logs into the separate authentication service to get a JWT.
        """
        if not self._http_session or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()

        auth_url = f"{self.auth_settings.url}/api/auth/login"
        credentials = {
            "cedula": self.auth_settings.cedula,
            "nombre": self.auth_settings.nombre,
            "contrasena": self.auth_settings.password,
        }

        try:
            logger.info(f"Authenticating with auth service at {auth_url}...")
            async with self._http_session.post(
                auth_url, json=credentials, timeout=10
            ) as response:
                response.raise_for_status()
                data = await response.json()
                self._translator_auth_token = data.get("accessToken")
                if self._translator_auth_token:
                    logger.info("Successfully authenticated and received JWT.")
                else:
                    raise ConnectionError(
                        "Authentication successful, but no access token received."  # noqa:E501
                    )
        except aiohttp.ClientError as e:
            logger.error(f"Failed to authenticate with auth service: {e}")
            raise ConnectionError(
                f"Could not authenticate with auth service: {e}"
            )  # noqa:E501

    async def connect(self):
        """
        Initializes the HTTP session and authenticates to get a token.
        """
        if self._http_session and not self._http_session.closed:
            return

        try:
            await self._authenticate_with_translator()
            logger.info("HTTP session for Cassandra translator is ready.")
        except Exception as e:
            logger.error(
                f"Failed to initialize HTTP session or authenticate: {e}"
            )  # noqa:E501
            await self.disconnect()
            raise

    async def disconnect(self):
        """Closes the HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
            logger.info("Cassandra translator HTTP session closed.")

    def _format_value(self, value: Any) -> str:
        """Formats a Python value into a SQL literal string."""
        if isinstance(value, str):
            return f"""'{value.replace("'", "''")}'"""
        if isinstance(value, (int, float, bool)):
            return str(value)
        if value is None:
            return "NULL"
        return f"'{str(value)}'"

    async def _execute_via_translator(
        self, sql_query: str
    ) -> List[Dict[str, Any]]:  # noqa:E501
        """
        Sends an SQL query to the external translator service for execution
        and correctly parses the nested response based on diagnostic logs.
        """
        if not self._http_session:
            raise ConnectionError(
                "HTTP session not initialized. Call connect() first."
            )  # noqa:E501

        if not self._translator_auth_token:
            raise ConnectionError("Not authenticated. Cannot execute query.")

        url = f"{self.translator_url}/api/translator/execute"
        payload = {"sql": sql_query, "keyspace": self.settings.keyspace}
        headers = {"Authorization": f"Bearer {self._translator_auth_token}"}

        try:
            logger.info(f"Executing SQL via translator: {sql_query}")
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                response.raise_for_status()
                data = await response.json()

                if not data.get("success"):
                    error_msg = data.get(
                        "message", "Unknown error from translator API"
                    )  # noqa:E501
                    logger.error(f"Translator API error: {error_msg}")
                    raise ConnectionError(
                        f"Translator API indicated failure: {error_msg}"
                    )

                execution_result = data.get("executionResult", {})
                if not execution_result.get("success"):
                    error_msg = execution_result.get(
                        "message", "Unknown execution error"
                    )
                    logger.error(f"Cassandra execution error: {error_msg}")
                    raise ConnectionError(
                        f"Cassandra execution failed: {error_msg}"
                    )  # noqa:E501

                # The actual data rows are nested inside
                # executionResult -> data -> rows
                result_data = execution_result.get("data", {})
                rows = result_data.get("rows")

                # For INSERT/UPDATE/DELETE, 'rows' can be null. For SELECT,
                # it's a list.
                # In all cases where rows are not returned, we return an
                # empty list
                # to match the test assertions
                # (e.g., `assert insert_result == []`).
                return rows if rows is not None else []

        except aiohttp.ClientResponseError as e:
            logger.error(
                f"Error from translator service: {e.status}, {e.message}"
            )  # noqa:E501
            raise ConnectionError(
                f"Failed to communicate with Cassandra translator: {e.status} {e.message}"  # noqa:E501
            )

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        return await self._execute_via_translator(sql)

    async def get(
        self, entity: str, pk_val: Any, pk_col: str
    ) -> Optional[Dict[str, Any]]:
        pk_val_formatted = self._format_value(pk_val)
        sql = f"SELECT * FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        results = await self.query(sql)
        return results[0] if results else None

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM {entity}"
        return await self.query(sql)

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        """Builds and executes an INSERT statement via the translator."""
        cols = ", ".join(payload.keys())
        vals = ", ".join(self._format_value(v) for v in payload.values())
        sql = f"INSERT INTO {entity} ({cols}) VALUES ({vals})"
        # The API returns no meaningful data for insert,
        # so we return the result
        # of the execution, which will be an empty list.
        return await self.query(sql)

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        set_clause = ", ".join(
            f"{k} = {self._format_value(v)}" for k, v in payload.items()
        )
        pk_val_formatted = self._format_value(pk_val)
        sql = f"UPDATE {entity} SET {set_clause} WHERE {pk_col} = {pk_val_formatted}"  # noqa:E501
        await self._execute_via_translator(sql)
        # The API doesn't return an affected row count for updates.
        # Returning 1 to signify success,
        # as per the abstract method's contract.
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        pk_val_formatted = self._format_value(pk_val)
        sql = f"DELETE FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        await self._execute_via_translator(sql)
        # The API doesn't return an affected row count for deletes.
        # Returning 1 to signify success.
        return 1

    async def count(self, entity: str) -> int:
        sql = f"SELECT COUNT(*) FROM {entity}"
        result = await self._execute_via_translator(sql)
        # Based on logs, the response is `[{'count': '2'}]`
        if result and isinstance(result, list) and len(result) > 0:
            # The count value is returned as a string.
            count_value = result[0].get("count", 0)
            return int(count_value)
        return 0

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self._execute_via_translator(ast.sql())

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self._execute_via_translator(ast.sql())

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self._execute_via_translator(ast.sql())

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        logger.warning(
            "Performing row-by-row bulk insert for Cassandra via translator. This may be slow."  # noqa:E501
        )
        count = 0
        import csv

        try:
            with open(file_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Filter out None values from the row
                    clean_row = {k: v for k, v in row.items() if v is not None}
                    if clean_row:
                        await self.insert(table_name, clean_row)
                        count += 1
            return count
        except FileNotFoundError:
            logger.error(f"Bulk insert file not found: {file_path}")
            return 0
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            raise
