# tests/test_query_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_customer_redis():
    c = PolyClient()
    rows = await c.query("SELECT * FROM customers WHERE customerId = 1")
    print("rows", rows)
    print("rows[0]", rows[0])
    print("rows[0]['companyName']", rows[0]["companyName"])
    assert rows and rows[0]["companyName"] == "Customer NRZBB"
