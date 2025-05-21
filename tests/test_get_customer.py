# tests/test_get_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_customer_postgres():
    c = PolyClient()
    doc = await c.get("customers", "ALFKI", "pg")
    assert doc["companyName"] == "Alfreds Futterkiste"


@pytest.mark.asyncio
async def test_get_customer_redis_string_by_default():
    c = PolyClient()
    doc = await c.get("Customer", "1:string", "redis")
    print("doc", doc)
    assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_hash():
    c = PolyClient({"data_type": "hash"})
    doc = await c.get("Customer", "1:hash", "redis")
    print("doc", doc)
    assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_json():
    c = PolyClient({"data_type": "json"})
    doc = await c.get("Customer", "1:json", "redis")
    print("doc", doc)
    assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_neo4j():
    c = PolyClient()
    doc = await c.get("customer", "ALFKI", "neo4j")
    assert doc["companyName"] == "Alfreds Futterkiste"
