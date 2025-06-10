# ---------------------------------------------------------------------------
# Connectors (very thin) – open/close per call for simplicity
# ---------------------------------------------------------------------------
import json
import logging

from typing import Dict, Any

import asyncpg
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import _camelize_keys, env


class PostgresConnector(Connector):
    def __init__(self, options: Dict = None) -> None:
        super().__init__(options)
        self._options = options
        self._host = env("POSTGRES_HOST", "localhost")
        self._port = int(env("POSTGRES_PORT", "5432"))
        self._user = env("POSTGRES_USER", "northwind")
        self._password = env("POSTGRES_PASSWORD", "northwind")
        self._database = env("POSTGRES_DB", "northwind")

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
        )

    async def ping(self) -> bool:
        conn = await self._connect()
        try:
            await conn.execute("SELECT 1")
            return True
        finally:
            await conn.close()

    async def count(self, table: str) -> int:
        conn = await self._connect()
        try:
            query = f"SELECT COUNT(*) AS n FROM {table}"
            logging.log(logging.WARNING, query)
            row = await conn.fetchrow(query)
            return int(row["n"])
        finally:
            await conn.close()

    async def get(self, table: str, pk: str) -> Dict[str, Any]:
        pk_col = "customer_id" if table == "customers" else "product_id"

        if table == "Product":
            pk_col = '"productID"'
        elif table == "Customer":
            pk_col = '"customerID"'

        conn = await self._connect()
        try:
            query = f"SELECT row_to_json(t) FROM {table} t WHERE {pk_col} = $1"
            logging.warning(f"Executing query: {query} with pk: {pk}")

            pk_val = int(pk) if pk.isdigit() else pk
            row = await conn.fetchrow(query, pk_val)
            if not row:
                return {}

                # The result from row_to_json is a string,
                # so it needs to be loaded.
            data = json.loads(row.get("row_to_json"))
            return _camelize_keys(data)
        finally:
            await conn.close()

    async def insert(self, table: str, payload: Dict[str, Any]) -> Any:
        """Inserts a new record into the specified table."""
        conn = await self._connect()
        try:
            # Use proper quoting for identifiers
            cols = ", ".join(f'"{k}"' for k in payload.keys())
            placeholders = ", ".join(f"${i + 1}" for i in range(len(payload)))
            values = list(payload.values())
            sql_query = f'INSERT INTO "{table}" ({cols})'
            sql_query += f" VALUES ({placeholders}) RETURNING *"
            msg = f"Executing INSERT: {sql_query} with values {values}"
            logging.warning(msg)

            row = await conn.fetchrow(sql_query, *values)
            return _camelize_keys(dict(row)) if row else {}
        finally:
            await conn.close()
