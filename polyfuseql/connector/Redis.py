import json
from contextlib import asynccontextmanager
from typing import Dict, Any

from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env
import redis.asyncio as aioredis


class RedisConnector(Connector):
    def __init__(self, options: Dict = None) -> None:
        super().__init__(options)
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._username = env("REDIS_USER", "northwind")
        self._password = env("REDIS_PASSWORD", "northwind")
        self._client: aioredis.Redis | None = None
        if options:
            self._options = options
        else:
            self._options = {"data_type": "string"}

    @asynccontextmanager
    async def _redis(self):
        if not self._client:
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                decode_responses=True,
                password=self._password,
            )
        try:
            yield self._client
        finally:
            pass  # keep connection open for reuse

    async def ping(self) -> bool:
        async with self._redis() as r:
            return await r.ping()

    async def count(self, namespace: str) -> int:
        prefix = f"{namespace}:*"
        total, cursor = 0, 0
        async with self._redis() as r:
            while True:
                c = await r.scan(cursor=cursor, match=prefix, count=1000)
                cursor, keys = c
                total += len(keys)
                if cursor == 0:  # fin del cursor
                    print("cursor was 0")
                    break
        return total

    async def get(self, namespace: str, pk: str) -> Dict[str, Any]:
        """
        Accept a format like :json or :hash or :string
        to get expected data type
        :param namespace: expected namespace to connect
        :param pk: identifier of the namespaced entity to get
        :return: Dictionary with the values of the entity
        """
        key = f"{namespace}:{pk}"
        print(key)
        data_type = self._options.get("data_type", "")
        match data_type:
            case "string":
                return await self.get_string(key)
            case "hash":
                return await self.get_hash(key)
            case "json":
                return await self.get_json(key)
            case _:
                raise NotImplementedError(f"Unknown data type: {data_type}")

    async def get_string(self, key: str) -> Dict:
        async with self._redis() as r:
            raw = await r.get(key)
            return json.loads(raw) if raw else {}

    async def get_hash(self, key: str) -> Dict | None:
        async with self._redis() as r:
            raw = await r.hgetall(key)
            return raw

    async def get_json(self, key: str) -> Dict:
        async with self._redis() as r:
            raw = await r.json().get(key)
            return raw

    async def insert(self, namespace: str, payload: Dict[str, Any]) -> Any:
        """
        Inserts a new record into Redis.
        The primary key must be in the payload.
        """
        pk_col = self._options.get("pk", "id")
        if pk_col not in payload:
            raise ValueError(f"Primary key '{pk_col}' not found in payload")

        key = f"{namespace}:{payload[pk_col]}"
        data_type = self._options.get("data_type", "string")
        error_msg = f"Unknown data type: {data_type}"

        async with self._redis() as r:
            match data_type:
                case "string":
                    await r.set(key, json.dumps(payload))
                case "hash":
                    await r.hset(key, mapping=payload)
                case "json":
                    await r.json().set(key, "$", payload)
                case _:
                    raise NotImplementedError(error_msg)
        return {"status": "inserted", "key": key, "backend": "redis"}
