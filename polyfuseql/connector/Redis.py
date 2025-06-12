import json
import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env
import redis.asyncio as aioredis


class RedisConnector(Connector):
    """Connector for Redis with persistent connection handling."""

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "northwind")
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        if not self._client:
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                decode_responses=True,
                password=self._password,
            )
            logging.info("Redis client initialized.")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            logging.info("Redis connection closed.")

    def _get_client(self) -> aioredis.Redis:
        if not self._client:
            raise ConnectionError(
                "RedisConnector is not connected. Call connect() first."
            )
        return self._client

    async def ping(self) -> bool:
        r = self._get_client()
        return await r.ping()

    async def count(self, namespace: str) -> int:
        r = self._get_client()
        prefix = f"{namespace.lower()}:*"
        total = 0
        cursor = 0
        while True:
            cur = await r.scan(cursor=cursor, match=prefix, count=1000)
            cursor, keys = cur
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def get(
        self, namespace: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")

        match data_type:
            case "string":
                raw = await r.get(key)
                return json.loads(raw) if raw else {}
            case "hash":
                raw_hash = await r.hgetall(key)
                return raw_hash
            case "json":
                raw_json = await r.json().get(key)
                return raw_json if raw_json else {}
            case _:
                raise NotImplementedError(f"Unsupported data type:{data_type}")

    async def insert(self, namespace: str, payload: Dict[str, Any]) -> Any:
        r = self._get_client()
        pk_col = self._options.get("pk", "id")
        pk_val = payload.get(pk_col)
        if not pk_val:
            pk_col_old = pk_col
            for key, value in payload.items():
                pk_col, pk_val = key, value
                break
            msg = (
                f"Primary key '{pk_col_old}' not found "
                f"in payload for Redis insert."
                f" Using the first column as id: {pk_col}"
            )
            logging.warning(msg)

        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")

        match data_type:
            case "string":
                await r.set(key, json.dumps(payload))
            case "hash":
                await r.hset(key, mapping=payload)
            case "json":
                await r.json().set(key, "$", payload)
            case _:
                raise NotImplementedError(f"Unknown data type: {data_type}")
        return {"status": "inserted", "key": key, "backend": "redis"}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        msg = "RedisConnector does not support raw SQL queries."
        raise NotImplementedError(msg)

    async def delete(self, namespace: str, pk_col: str, pk_val: Any) -> int:
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        print("redis-delete-key", key)
        deleted_count = await r.delete(key)
        return deleted_count
