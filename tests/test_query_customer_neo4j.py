# tests/test_query_customer_neo4j.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_customer_neo4j():
    async with PolyClient() as c:
        rows = await c.execute(
            "SELECT * FROM customer WHERE customerID = 'ALFKI'", engine="neo4j"
        )
        assert rows and rows[0]["companyName"] == "Alfreds Futterkiste"
