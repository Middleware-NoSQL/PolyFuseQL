import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_product_postgres():
    async with PolyClient() as c:
        # This will now execute against postgres because engine is specified
        rows = await c.execute(
            'SELECT * FROM products WHERE "productID" = 1', engine="postgres"
        )
        assert rows and rows[0]["productName"] == "Chai"


@pytest.mark.asyncio
async def test_get_product_redis_string_by_default():
    async with PolyClient() as c:
        doc = await c.get("Product", "1:1:1:string", "redis")
        print("doc", doc)
        assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_redis_hash():
    async with PolyClient({"data_type": "hash"}) as c:
        doc = await c.get("Product", "1:1:1:hash", "redis")
        print("doc", doc)
        assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_redis_json():
    async with PolyClient({"data_type": "json"}) as c:
        doc = await c.get("Product", "1:1:1:json", "redis")
        print("doc", doc)
        assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_neo4j():
    async with PolyClient() as c:
        # Use the logical name from the catalogue
        doc = await c.get("product", "1", "neo4j")
        assert doc["productName"] == "Chai"
