# tests/test_get_product.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_product_postgres():
    c = PolyClient()
    doc = await c.get("products", "1", "pg")
    print("doc", doc)
    assert doc["productName"] == "Chai"


@pytest.mark.asyncio
async def test_get_product_redis():
    c = PolyClient()
    doc = await c.get("product", "1", "redis")
    assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_neo4j():
    c = PolyClient()
    doc = await c.get("product", "1", "neo4j")
    assert doc["productName"] == "Chai"
