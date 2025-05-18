# tests/test_get_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_get_customer():
    c = PolyClient()
    doc = await c.get("customers", "ALFKI")
    assert doc["companyName"] == "Alfreds Futterkiste"
