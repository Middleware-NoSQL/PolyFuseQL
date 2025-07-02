# tests/test_query_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_customer_redis_string():
    options = {"data_type": "string", "split_data_type": ""}
    async with PolyClient(options=options) as c:
        sql = "SELECT * FROM \"Customer\" WHERE customer = '1:string'"
        rows = await c.execute(sql, engine="redis")
        assert rows and rows[0]["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_query_customer_redis_hash():
    options = {"data_type": "hash", "split_data_type": ""}
    async with PolyClient(options=options) as c:
        sql = "SELECT * FROM Customer WHERE customer = '1:hash'"
        rows = await c.execute(sql, engine="redis")
        assert rows and rows[0]["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_query_customer_redis_json():
    options = {"data_type": "json", "split_data_type": ""}
    async with PolyClient(options=options) as c:
        sql = "SELECT * FROM Customer WHERE customer = '1:json'"
        rows = await c.execute(sql, engine="redis")
        assert rows and rows[0]["companyName"] == "Customer NRZBB"
