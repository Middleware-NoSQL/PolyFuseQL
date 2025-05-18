# tests/test_basic_count.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_count_customers():
    c = PolyClient()
    cnt = await c.count("customers")
    assert cnt == 91
