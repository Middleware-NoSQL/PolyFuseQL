# ---------------------------------------------------------------------------
# Connectors (very thin) – open/close per call for simplicity
# ---------------------------------------------------------------------------
import logging

from typing import Dict, Any

import asyncpg

from polyfuseql.utils.utils import _camelize_keys, _env


class PostgresConnector:
    def __init__(self) -> None:
        self._host = _env("POSTGRES_HOST", "localhost")
        self._port = int(_env("POSTGRES_PORT", "5432"))
        self._user = _env("POSTGRES_USER", "northwind")
        self._password = _env("POSTGRES_PASSWORD", "northwind")
        self._database = _env("POSTGRES_DB", "northwind")

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
        pk_col = "customer_id" if table == "customers" else "productid"
        conn = await self._connect()
        try:
            query = f"SELECT row_to_json(t) FROM {table} t WHERE {pk_col} = $1"
            logging.log(logging.INFO, "GET BEFORE AWAIT" + query)
            row = await conn.fetchval(query, pk)
            logging.log(logging.INFO, "GET AFTER AWAIT" + row)
            logging.log(logging.INFO, "GET AFTER AWAIT" + str(type(row)))
            return _camelize_keys(row) if row else {}
        finally:
            await conn.close()
