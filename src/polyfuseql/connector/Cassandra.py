import logging
import csv
import aiofiles
from typing import Any, Dict, List, Optional

import aiohttp
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import BatchStatement, SimpleStatement
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

        # Native connection for bulk loading
        self._native_cluster = None
        self._native_session = None

        logger.info(
            f"CassandraConnector initialized for translator at {self.translator_url}"
            # noqa:E501
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
                        "Authentication successful, but no access token received."
                        # noqa:E501
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
        """Closes the HTTP session and Native connection."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
            logger.info("Cassandra translator HTTP session closed.")

        if self._native_cluster:
            self._native_cluster.shutdown()
            self._native_cluster = None
            self._native_session = None

    def _connect_native(self):
        """Establishes direct connection to Cassandra for admin/bulk tasks."""
        if self._native_session:
            return

        hosts = [self.settings.host] if self.settings.host else ["localhost"]
        port = self.settings.port or 9042

        # Use credentials from settings or fall back to container defaults (cassandra/cassandra)
        username = getattr(self.settings, "user", "cassandra")
        password = getattr(self.settings, "password", "cassandra")

        auth_provider = PlainTextAuthProvider(username=username, password=password)

        logger.info(
            f"Connecting natively to Cassandra at {hosts}:{port} with user {username}..."
        )
        self._native_cluster = Cluster(
            contact_points=hosts, port=port, auth_provider=auth_provider
        )
        self._native_session = self._native_cluster.connect()

        ks = self.settings.keyspace or "tpch"
        self._native_session.execute(
            f"""
            CREATE KEYSPACE IF NOT EXISTS {ks}
            WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
        """
        )
        self._native_session.set_keyspace(ks)

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
            # Auto-connect if needed, or raise if strict lifecycle management is preferred
            await self.connect()

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
                return rows if rows is not None else []

        except aiohttp.ClientResponseError as e:
            logger.error(
                f"Error from translator service: {e.status}, {e.message}"
            )  # noqa:E501
            raise ConnectionError(
                f"Failed to communicate with Cassandra translator: {e.status} {e.message}"
                # noqa:E501
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
        """
        Builds and executes an INSERT statement via the translator.
        [FIX] Uses catalogue schema to cast values to correct types before formatting
        to ensure integers are not quoted in the generated SQL.
        """
        formatted_values = []
        schema = self.catalogue.get_schema(entity)

        for col, val in payload.items():
            # Check schema to see if we need to force cast from string to number
            # This prevents _format_value from wrapping integers in quotes
            if schema and "columns" in schema and col in schema["columns"]:
                col_type = schema["columns"][col]
                logging.info(f"cassandra insert col_type: {col_type}")
                if col_type == "int":
                    try:
                        val = int(val)
                        logging.info(f"val: {val} of type should be int: {type(val)}")
                    except ValueError as ve:
                        # Let _format_value handle it if cast fails
                        logging.info(f"Error: {ve}")
                elif col_type in ("decimal", "float"):
                    try:
                        val = float(val)
                        logging.info(
                            f"val: {val} of type should be float/decimal: {type(val)}"
                        )
                    except ValueError as ve:
                        logging.info(f"Error: {ve}")

            formatted_values.append(self._format_value(val))

        cols = ", ".join(payload.keys())
        vals = ", ".join(formatted_values)
        sql = f"INSERT INTO {entity} ({cols}) VALUES ({vals})"

        logger.info(f"Cassandra insert SQL generated: {sql}")
        print(f"Cassandra insert SQL generated: {sql}")

        # The API returns no meaningful data for insert
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
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        pk_val_formatted = self._format_value(pk_val)
        sql = f"DELETE FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        await self._execute_via_translator(sql)
        return 1

    async def count(self, entity: str) -> int:
        sql = f"SELECT COUNT(*) FROM {entity}"
        result = await self._execute_via_translator(sql)
        if result and isinstance(result, list) and len(result) > 0:
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
        """
        Directly connects to Cassandra to CREATE TABLE and INSERT data.
        Bypasses translator for setup/bulk loading to ensure schema exists and for speed.
        [FIX] Handles "Invalid STRING constant" errors by strictly converting types
        and ignoring individual row failures to ensure as much data as possible is loaded.
        """
        self._connect_native()

        schema = self.catalogue.get_schema(table_name)
        if not schema:
            logger.error(f"No schema for {table_name}")
            return 0

        # 1. Drop and Create Table (DDL)
        self._native_session.execute(f"DROP TABLE IF EXISTS {table_name}")

        cols_def = []
        type_map = {
            "int": "int",
            "str": "text",
            "decimal": "decimal",
            "date": "date",
            "float": "float",
        }

        for col, dtype in schema["columns"].items():
            cql_type = type_map.get(dtype, "text")
            cols_def.append(f"{col} {cql_type}")

        pk = schema["pk"]
        if isinstance(pk, list):
            pk_str = f"({pk[0]}), {', '.join(pk[1:])}"
        else:
            pk_str = pk

        create_sql = (
            f"CREATE TABLE {table_name} ({', '.join(cols_def)}, PRIMARY KEY ({pk_str}))"
        )
        logger.info(f"Creating table: {create_sql}")
        self._native_session.execute(create_sql)

        # 2. Prepared Insert
        col_names = list(schema["columns"].keys())
        phs = ", ".join(["?"] * len(col_names))
        insert_stmt = self._native_session.prepare(
            f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({phs})"
        )

        # 3. Batch Load
        count = 0
        inserted = 0
        batch = BatchStatement()
        BATCH_SIZE = 50  # Reduced batch size to minimize fallout from one bad row

        try:
            async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
                content = await f.read()
                lines = [l for l in content.splitlines() if l.strip()]
                reader = csv.reader(lines, delimiter="|")

                for row_idx, row in enumerate(reader):
                    if len(row) > len(col_names):
                        row = row[: len(col_names)]

                    # [DEBUG] Verbose logging for raw row data (Info level for visibility)
                    logger.info(f"Raw row {row_idx}: {row}")

                    clean_row = []
                    valid_row = True
                    for i, col in enumerate(col_names):
                        val = row[i]
                        ctype = schema["columns"][col]

                        # [FIX] Strict Type Conversion Logic
                        # If catalogue says "int", we MUST cast to int.
                        # If cast fails, we flag the row invalid rather than passing string
                        try:
                            if ctype == "int":
                                # Remove quotes if present to ensure clean int conversion
                                val = int(str(val).replace("'", "").replace('"', ""))
                            elif ctype in ["decimal", "float"]:
                                val = float(str(val).replace("'", "").replace('"', ""))
                            # Cassandra Date: keep string 'YYYY-MM-DD'
                            # Strings: keep as is
                        except ValueError as e:
                            # Log specific failure for debugging "Invalid STRING constant"
                            logger.warning(
                                f"Row {row_idx} skipped. Type conversion failed for col '{col}' value '{val}': {e}"
                            )
                            valid_row = False
                            break

                        clean_row.append(val)

                    if valid_row:
                        # [DEBUG] Verbose logging for converted row data
                        logger.info(f"Row {row_idx} converted: {clean_row}")
                        batch.add(insert_stmt, clean_row)
                        count += 1

                    if count >= BATCH_SIZE:
                        try:
                            self._native_session.execute(batch)
                            inserted += count
                        except Exception as e:
                            logger.error(
                                f"Batch failed for {table_name} at row {row_idx}: {e}"
                            )
                            # Proceed to next batch
                        finally:
                            count = 0
                            batch = BatchStatement()

                if count > 0:
                    try:
                        self._native_session.execute(batch)
                        inserted += count
                    except Exception as e:
                        logger.error(f"Final batch failed for {table_name}: {e}")

            return inserted

        except Exception as e:
            logger.error(f"Bulk insert failed for {table_name}: {e}")
            return 0
