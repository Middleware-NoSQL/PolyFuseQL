# tests/test_query_product.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_product_postgres():
    c = PolyClient()
    rows = await c.query("SELECT * FROM products WHERE productId = 1")
    assert rows and rows[0]["productName"] == "Chai"
