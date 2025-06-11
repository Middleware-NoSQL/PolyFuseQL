import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_redis_string():
    """Tests INSERT into Redis with the 'string' data type."""
    async with PolyClient(options={"data_type": "string"}) as client:
        sql = "INSERT INTO Customer (id, name) "
        sql += "VALUES ('rd_str_2', 'Redis String User')"
        result = await client.execute(sql, engine="redis")
        assert result["status"] == "inserted"
        assert result["key"] == "Customer:rd_str_2"


@pytest.mark.asyncio
async def test_insert_redis_hash():
    """Tests INSERT into Redis with the 'hash' data type."""
    async with PolyClient(options={"data_type": "hash"}) as client:
        sql = "INSERT INTO Customer (id, name) "
        sql += "VALUES ('rd_hash_1', 'Redis Hash User')"
        result = await client.execute(sql, engine="redis")
        assert result["status"] == "inserted"
        assert result["key"] == "Customer:rd_hash_1"


@pytest.mark.asyncio
async def test_insert_redis_json():
    """Tests INSERT into Redis with the 'json' data type."""
    async with PolyClient(options={"data_type": "json"}) as client:
        sql = "INSERT INTO Customer (id, name) "
        sql += "VALUES ('rd_json_1', 'Redis Json User')"
        result = await client.execute(sql, engine="redis")
        assert result["status"] == "inserted"
        assert result["key"] == "Customer:rd_json_1"
