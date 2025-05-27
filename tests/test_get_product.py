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
async def test_get_product_redis_string_by_default():
    c = PolyClient()
    doc = await c.get("Product", "1:1:1:string", "redis")
    print("doc", doc)
    assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_redis_hash():
    c = PolyClient({"data_type": "hash"})
    doc = await c.get("Product", "1:1:1:hash", "redis")
    print("doc", doc)
    assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_redis_json():
    c = PolyClient({"data_type": "json"})
    doc = await c.get("Product", "1:1:1:json", "redis")
    print("doc", doc)
    assert doc["productName"] == "Product HHYDP"


@pytest.mark.asyncio
async def test_get_product_neo4j():
    c = PolyClient()
    doc = await c.get("product", "1", "neo4j")
    assert doc["productName"] == "Chai"
