# tests/test_query_unsupported.py
import pytest
from polyfuseql.client.PolyClient import PolyClient

pytestmark = pytest.mark.asyncio


async def test_query_unsupported():
    c = PolyClient()
    with pytest.raises(NotImplementedError):
        await c.query("SELECT name FROM customers")
