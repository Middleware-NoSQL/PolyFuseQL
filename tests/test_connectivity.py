import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_ping_all():
    async with PolyClient() as c:
        assert await c.pg.ping()
        assert await c.rd.ping()
        assert await c.nj.ping()
