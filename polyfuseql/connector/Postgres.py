import json
import logging
from typing import Dict, Any, Optional, List

import asyncpg
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import _camelize_keys, env, _snake_case


class PostgresConnector(Connector):
    """Connector for PostgreSQL with persistent connection handling."""

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        self._host = env("POSTGRES_HOST", "localhost")
        self._port = int(env("POSTGRES_PORT", "5432"))
        self._user = env("POSTGRES_USER", "northwind")
        self._password = env("POSTGRES_PASSWORD", "northwind")
        self._database = env("POSTGRES_DB", "northwind")
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
        query = f'SELECT COUNT(*) AS n FROM "{table}"'
        row = await conn.fetchrow(query)
        return int(row["n"]) if row else 0

    async def get(
        self, table: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        conn = self._get_conn()

        query = "SELECT row_to_json(t) FROM "
        query += f" {table} t WHERE {pk_col} = $1"  # noqa: F501
        print("postgres-conector-get-query", query)
        print("postgres-conector-get-pk_val", pk_val)
        print("postgres-conector-get-pk_val-type", type(pk_val))
        row = await conn.fetchrow(query, pk_val)
        if not row:
            return {}
        print("Postgres-get-row", row)
        print("Postgres-get-row-get", row.get("row_to_json"))
        data = json.loads(row.get("row_to_json"))
        return _camelize_keys(data) if data else {}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        records = (
            await conn.fetch(sql, *params) if params else await conn.fetch(sql)
        )  # noqa: F501
        return [_camelize_keys(dict(r)) for r in records]

    async def insert(self, table: str, payload: Dict[str, Any]) -> Any:
        conn = self._get_conn()
        db_payload = {_snake_case(k): v for k, v in payload.items()}
        cols = ", ".join(f'"{k}"' for k in db_payload.keys())
        placeholders = ", ".join(f"${i + 1}" for i in range(len(db_payload)))
        values = list(db_payload.values())
        sql_query = f'INSERT INTO "{table}" ({cols}) '
        sql_query += f"VALUES ({placeholders}) RETURNING *"  # noqa: F501
        row = await conn.fetchrow(sql_query, *values)
        return _camelize_keys(dict(row)) if row else {}
