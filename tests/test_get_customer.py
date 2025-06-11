import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_customer_postgres():
    async with PolyClient() as c:
        # Note: The modified schema uses "Customer" table in CamelCase
        doc = await c.get("customers", "ALFKI", "pg")
        assert doc["companyName"] == "Alfreds Futterkiste"


@pytest.mark.asyncio
async def test_get_customer_redis_string_by_default():
    async with PolyClient() as c:
        doc = await c.get(
            "Customer", "1:string", "redis"
        )  # Use the logical name and simple PK
        print(doc.keys())
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_hash():
    async with PolyClient({"data_type": "hash"}) as c:
        doc = await c.get("Customer", "1:hash", "redis")
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_json():
    async with PolyClient({"data_type": "json"}) as c:
        doc = await c.get("Customer", "1:json", "redis")
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_neo4j():
    async with PolyClient() as c:
        u = "customer"
        id = "ALFKI"
        eng = "neo4j"
        doc = await c.get(u, id, eng)
        assert doc["companyName"] == "Alfreds Futterkiste"
