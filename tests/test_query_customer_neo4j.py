# tests/test_query_customer_neo4j.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_customer_neo4j():
    c = PolyClient()
    rows = await c.query("SELECT * FROM customer WHERE customerId = 'ALFKI'")
    assert rows and rows[0]["companyName"] == "Alfreds Futterkiste"
