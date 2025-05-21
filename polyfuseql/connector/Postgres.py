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
        conn = await self._connect()
        try:
            query = f"SELECT row_to_json(t) FROM {table} t WHERE {pk_col} = $1"
            print("GET BEFORE AWAIT" + query)
            if pk.isdigit():
                pk_val = int(pk)
            else:
                pk_val = pk
            row = await conn.fetchrow(query, pk_val)
            print("GET AFTER AWAIT" + str(row))
            print("GET AFTER AWAIT" + str(type(row)))
            row = json.loads(row.get("row_to_json"))
            return _camelize_keys(row) if row else {}
        finally:
            await conn.close()
