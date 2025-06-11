# tests/test_query_product.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_product_postgres():
    async with PolyClient() as c:
        # Use the catalogue's default backend for 'products' (Postgres)
        rows = await c.execute(
            "SELECT * FROM products WHERE productID = 1", engine="postgres"
        )
        assert rows and rows[0]["productName"] == "Chai"
