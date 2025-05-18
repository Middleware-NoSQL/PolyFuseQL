import json
from contextlib import asynccontextmanager
from typing import Dict, Any

from polyfuseql.utils.utils import _env
import redis.asyncio as aioredis


class RedisConnector:
    def __init__(self) -> None:
        self._host = _env("REDIS_HOST", "localhost")
        self._port = int(_env("REDIS_PORT", "6379"))
        self._client: aioredis.Redis | None = None

    @asynccontextmanager
    async def _redis(self):
        if not self._client:
            self._client = aioredis.Redis(
                host=self._host, port=self._port, decode_responses=True
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
        async with self._redis() as r:
            cursor = "0"
            total = 0
            while cursor != 0:
                cur = await r.scan(cursor=cursor, match=prefix, count=1000)
                cursor, keys = cur
                total += len(keys)
            return total

    async def get(self, namespace: str, pk: str) -> Dict[str, Any]:
        key = f"{namespace}:{pk}"
        async with self._redis() as r:
            raw = await r.get(key)
            return json.loads(raw) if raw else {}
