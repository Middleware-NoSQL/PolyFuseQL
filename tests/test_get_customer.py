# tests/test_get_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_customer_postgres():
    c = PolyClient()
    doc = await c.get("customers", "ALFKI", "pg")
    assert doc["companyName"] == "Alfreds Futterkiste"


@pytest.mark.asyncio
async def test_get_customer_redis():
    c = PolyClient()
    doc = await c.get("customer", "1", "redis")
    assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_neo4j():
    c = PolyClient()
    doc = await c.get("customer", "ALFKI", "neo4j")
    assert doc["companyName"] == "Alfreds Futterkiste"
