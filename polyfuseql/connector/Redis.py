import json
from contextlib import asynccontextmanager
from typing import Dict, Any

from polyfuseql.utils.utils import env
import redis.asyncio as aioredis


class RedisConnector:
    def __init__(self) -> None:
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
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
        key = f"{namespace}:{pk}"
        print(key)
        async with self._redis() as r:
            raw = await r.get(key)
            return json.loads(raw) if raw else {}
