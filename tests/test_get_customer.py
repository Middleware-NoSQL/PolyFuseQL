import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_customer_postgres():
    async with PolyClient() as c:
        # Note: The modified schema uses "Customer" table in CamelCase
        doc = await c.get(
            "customers",
            "ALFKI",
            primary_key_column="customer_Id",
            engine="postgres",  # noqa: F501
        )
        assert doc["companyName"] == "Alfreds Futterkiste"


@pytest.mark.asyncio
async def test_get_customer_redis_string_by_default():
    async with PolyClient() as c:
        doc = await c.get(
            "Customer",
            "1:string",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )  # Use the logical name and simple PK
        print(doc.keys())
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_hash():
    async with PolyClient({"data_type": "hash"}) as c:
        doc = await c.get(
            "Customer",
            "1:hash",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_redis_json():
    async with PolyClient({"data_type": "json"}) as c:
        doc = await c.get(
            "Customer",
            "1:json",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )
        assert doc["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_get_customer_neo4j():
    async with PolyClient() as c:
        u = "customer"
        id = "ALFKI"
        eng = "neo4j"
        doc = await c.get(u, id, primary_key_column="customerID", engine=eng)
        assert doc["companyName"] == "Alfreds Futterkiste"
