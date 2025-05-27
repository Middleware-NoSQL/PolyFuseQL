# tests/test_query_customer.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_customer_redis_string():
    options = {"data_type": "string", "split_data_type": ""}
    c = PolyClient(options=options)
    sql = "SELECT * FROM \"Customer\" WHERE customer = '1:string'"
    rows = await c.query(sql, engine="redis")
    assert rows and rows[0]["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_query_customer_redis_hash():
    options = {"data_type": "hash", "split_data_type": ""}
    c = PolyClient(options=options)
    rows = await c.query(
        "SELECT * FROM \"Customer\" WHERE customer = '1:hash'", engine="redis"
    )
    assert rows and rows[0]["companyName"] == "Customer NRZBB"


@pytest.mark.asyncio
async def test_query_customer_redis_json():
    options = {"data_type": "json", "split_data_type": ""}
    c = PolyClient(options=options)
    rows = await c.query(
        "SELECT * FROM \"Customer\" WHERE customer = '1:json'", engine="redis"
    )
    assert rows and rows[0]["companyName"] == "Customer NRZBB"
