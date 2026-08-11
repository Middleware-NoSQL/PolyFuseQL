import json
import logging
import csv
from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncpg
import aiofiles

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import _camelize_keys, _snake_case
from sqlglot import exp


class PostgresConnector(Connector):
    """Connector for PostgreSQL with persistent connection handling."""

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a native SQL JOIN query."""
        return await self.query(ast.sql())

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        """Not needed for this connector"""
        pass

    def __init__(self, catalogue: Optional[Catalogue] = None) -> None:
        super().__init__(catalogue=catalogue)
        self._host = settings.postgres.host
        self._port = settings.postgres.port
        self._user = settings.postgres.user
        self._password = settings.postgres.password
        self._database = settings.postgres.db
        self._connection: Optional[asyncpg.Connection] = None

    async def connect(self) -> None:
        if not self._connection or self._connection.is_closed():
            logger = logging.getLogger("uvicorn.error")
            logger.debug(
                f"host: {self._host}, port: {self._port}, user: {self._user}, "
                f"password: {self._password}"
            )
            self._connection = await asyncpg.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
            )
            logging.info("PostgreSQL connection established.")

    async def disconnect(self) -> None:
        if self._connection and not self._connection.is_closed():
            await self._connection.close()
            self._connection = None
            logging.info("PostgreSQL connection closed.")

    def _get_conn(self) -> asyncpg.Connection:
        if not self._connection or self._connection.is_closed():
            raise ConnectionError(
                "PostgresConnector is not connected. Call connect() first."
            )
        return self._connection

    async def ping(self) -> bool:
        conn = self._get_conn()
        return await conn.execute("SELECT 1") is not None

    async def count(self, table: str) -> int:
        conn = self._get_conn()
        query = f'SELECT COUNT(*) AS n FROM "{table.lower()}"'
        row = await conn.fetchrow(query)
        return int(row["n"]) if row else 0

    async def get(self, table: str, pk_col: str, pk_val: Any) -> Dict:
        # TODO Correctfully use of the select logic if the GET will be used
        #  liske that
        if not isinstance(pk_col, str):
            msg = "Primary key column name must be a string, got "
            msg += f"{type(pk_col).__name__}"
            raise TypeError(msg)
        conn = self._get_conn()
        table_name = table.lower()
        query = f'SELECT row_to_json(t) FROM "{table_name}" t '
        query += f'WHERE "{pk_col}" = $1'
        row = await conn.fetchrow(query, pk_val)
        if not row:
            return {}
        data = json.loads(row.get("row_to_json"))
        return _camelize_keys(data) if data else {}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        if params:
            records = await conn.fetch(sql, *params)
        else:
            records = await conn.fetch(sql)
        return [_camelize_keys(dict(r)) for r in records]

    async def insert(self, table: str, payload: Dict[str, Any]) -> Any:
        conn = self._get_conn()
        table_name = table.lower()
        db_payload = {_snake_case(k): v for k, v in payload.items()}
        cols = ", ".join(f'"{k}"' for k in db_payload.keys())
        ph = ", ".join(f"${i + 1}" for i in range(len(db_payload)))
        values = list(db_payload.values())
        sql_query = f'INSERT INTO "{table_name}" ({cols}) '
        sql_query += f"VALUES ({ph}) RETURNING *"
        row = await conn.fetchrow(sql_query, *values)
        return _camelize_keys(dict(row)) if row else {}

    async def delete(self, table: str, pk_col: str, pk_val: Any) -> int:
        conn = self._get_conn()
        table_name = table.lower()
        db_pk_col = _snake_case(pk_col)
        query = f'DELETE FROM "{table_name}" WHERE "{db_pk_col}" = $1'
        result = await conn.execute(query, pk_val)
        deleted_count = int(result.split(" ")[1])
        return deleted_count

    async def update(
        self, table: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        conn = self._get_conn()
        table_name = table.lower()
        dpc = _snake_case(pk_col)
        set_clauses = []
        values = []
        for i, (key, value) in enumerate(payload.items()):
            db_key = _snake_case(key)
            set_clauses.append(f'"{db_key}" = ${i + 1}')
            values.append(value)
        scs = ", ".join(set_clauses)
        values.append(pk_val)
        query = f'UPDATE "{table_name}" SET {scs}'
        query += f' WHERE "{dpc}" = ${len(values)}'
        result = await conn.execute(query, *values)
        updated_count = int(result.split(" ")[1])
        return updated_count

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self.query(ast.sql())

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a simple aggregation query (no GROUP BY)."""
        return await self.query(ast.sql())

    async def bulk_insert(self, t_name: str, file_path: str) -> int:
        conn = self._get_conn()
        schema = self.catalogue.get_schema(t_name)
        if not schema:
            raise ValueError(f"No schema found for table '{t_name}'")

        columns_schema = schema["columns"]
        ordered_cols = list(columns_schema.keys())

        def cast_value(value, col_name):
            col_type = columns_schema.get(col_name)
            if value is None or value == "":
                return None
            try:
                if col_type in ("int", "bigint"):
                    return int(value)
                if col_type in ("decimal", "real", "float", "double precision"):
                    return float(value)
                if col_type == "date":
                    return datetime.strptime(value, "%Y-%m-%d").date()
                if col_type == "timestamp":
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Fallback for malformed or incompatible data
                return value
            return value

        recs_ins = []
        try:
            async with aiofiles.open(
                file_path, mode="r", encoding="utf-8", newline=""
            ) as f:
                content = await f.read()
                # Handle empty trailing lines
                lines = [line for line in content.splitlines() if line.strip()]
                reader = csv.reader(lines, delimiter="|")

                for row in reader:
                    # Remove trailing empty field from pipe delimiter if present
                    if len(row) > len(ordered_cols):
                        row = row[: len(ordered_cols)]

                    if len(row) != len(ordered_cols):
                        msg = f"Skipping malformed row in {t_name}: "
                        msg += f"len={len(row)} expected={len(ordered_cols)}"
                        logging.warning(msg)
                        continue

                    processed_row = tuple(
                        cast_value(val, col) for val, col in zip(row, ordered_cols)
                    )
                    recs_ins.append(processed_row)
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            return 0

        if not recs_ins:
            return 0

        async with conn.transaction():
            # Truncate first to ensure clean state for benchmark
            await conn.execute(f'TRUNCATE TABLE "{t_name.lower()}" CASCADE;')
            await conn.copy_records_to_table(
                t_name.lower(), records=recs_ins, columns=ordered_cols
            )

        return len(recs_ins)
