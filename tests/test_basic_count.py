# tests/test_basic_count.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_count_customers_postgres():
    c = PolyClient()
    cnt = await c.count("customers", backend="pg")
    assert cnt == 91


@pytest.mark.asyncio
async def test_count_customers_redis():
    c = PolyClient()
    cnt = await c.count("customer", backend="redis")
    assert cnt == 89


@pytest.mark.asyncio
async def test_count_customers_neo4j():
    c = PolyClient()
    cnt = await c.count("customer", backend="neo4j")
    assert cnt == 91
