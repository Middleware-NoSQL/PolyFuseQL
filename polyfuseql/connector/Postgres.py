import json
import logging
import csv
from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncpg
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import _camelize_keys, env, _snake_case
from sqlglot import exp


class PostgresConnector(Connector):
    """Connector for PostgreSQL with persistent connection handling."""

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a native SQL JOIN query."""
        return await self.query(ast.sql())

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        pass

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        self._host = env("POSTGRES_HOST", "localhost")
        self._port = int(env("POSTGRES_PORT", "5432"))
        self._user = env("POSTGRES_USER", "tpch")
        self._password = env("POSTGRES_PASSWORD", "tpch")
        self._database = env("POSTGRES_DB", "tpch")
        self._connection: Optional[asyncpg.Connection] = None

    async def connect(self) -> None:
        if not self._connection or self._connection.is_closed():
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
        # Ensure table name is properly quoted to handle case sensitivity
        query = f'SELECT COUNT(*) AS n FROM "{table.lower()}"'
        row = await conn.fetchrow(query)
        return int(row["n"]) if row else 0

    async def get(self, table: str, pk_col: str, pk_val: Any) -> Dict:
        conn = self._get_conn()
        query = f'SELECT row_to_json(t) FROM "{table}" t WHERE "{pk_col}" = $1'
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
        db_payload = {_snake_case(k): v for k, v in payload.items()}
        cols = ", ".join(f'"{k}"' for k in db_payload.keys())
        ph = ", ".join(f"${i + 1}" for i in range(len(db_payload)))
        values = list(db_payload.values())
        sql_query = f'INSERT INTO "{table}" ({cols}) VALUES ({ph}) RETURNING *'
        row = await conn.fetchrow(sql_query, *values)
        return _camelize_keys(dict(row)) if row else {}

    async def delete(self, table: str, pk_col: str, pk_val: Any) -> int:
        conn = self._get_conn()
        db_pk_col = _snake_case(pk_col)
        query = f'DELETE FROM "{table}" WHERE "{db_pk_col}" = $1'
        result = await conn.execute(query, pk_val)
        deleted_count = int(result.split(" ")[1])
        return deleted_count

    async def update(
        self, table: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        conn = self._get_conn()
        dpc = _snake_case(pk_col)
        set_clauses = []
        values = []
        for i, (key, value) in enumerate(payload.items()):
            db_key = _snake_case(key)
            set_clauses.append(f'"{db_key}" = ${i + 1}')
            values.append(value)
        scs = ", ".join(set_clauses)
        values.append(pk_val)
        query = f'UPDATE "{table}" SET {scs} WHERE "{dpc}" = ${len(values)}'
        result = await conn.execute(query, *values)
        updated_count = int(result.split(" ")[1])
        return updated_count

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self.query(ast.sql())

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a simple aggregation query (no GROUP BY)."""
        return await self.query(ast.sql())

    async def bulk_insert(self, t_name: str, file_path: str) -> int:
        """
        Performs a high-performance bulk insert using PostgreSQL's COPY command
        This version includes data type conversion based on the
        TPC-H schema to fix test errors.
        """
        conn = self._get_conn()

        # Fetch column types from the database to perform accurate casting
        query = """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' \
                  AND table_name = $1
                ORDER BY ordinal_position; \
                """
        db_columns_info = await conn.fetch(query, t_name.lower())
        msg = f"Could not find schema for table '{t_name}'. Does it exist?"
        if not db_columns_info:
            raise ValueError(msg)

        type_map = {c["column_name"]: c["data_type"] for c in db_columns_info}
        ord_col = [c["column_name"] for c in db_columns_info]

        def cast_value(value, col_name):
            col_type = type_map.get(col_name)
            if value is None or value == "":
                return None
            if col_type in ("integer", "bigint"):
                return int(value)
            if col_type in ("numeric", "decimal", "real", "double precision"):
                return float(value)
            if col_type == "date":
                return datetime.strptime(value, "%Y-%m-%d").date()
            if col_type == "timestamp":
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return value

        recs_ins = []
        with open(file_path, "r") as f:
            reader = csv.reader(f, delimiter="|")
            for row in reader:
                row = row[:-1]
                msg = f"Skipping malformed row in {t_name}: {row}"
                if len(row) != len(ord_col):
                    logging.warning(msg)
                    continue

                processed_row = tuple(
                    cast_value(val, col) for val, col in zip(row, ord_col)
                )
                recs_ins.append(processed_row)

        async with conn.transaction():
            # For testing, ensure the table is clean before inserting
            await conn.execute(f'TRUNCATE TABLE "{t_name.lower()}" CASCADE;')
            await conn.copy_records_to_table(t_name.lower(), records=recs_ins)

        return len(recs_ins)
