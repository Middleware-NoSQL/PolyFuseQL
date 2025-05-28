import pytest

from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_redis_string():
    client = PolyClient(options={"data_type": "string"})
    sql = "INSERT INTO customer (id, name) VALUES ('1', 'RedisUser')"
    result = await client.insert(sql, engine="redis")
    assert result["status"] == "inserted"
    assert result["key"].startswith("customer:")


@pytest.mark.asyncio
async def test_insert_redis_hash():
    client = PolyClient(options={"data_type": "hash"})
    sql = "INSERT INTO customer (id, name) VALUES ('2', 'RedisHashUser')"
    result = await client.insert(sql, engine="redis")
    assert result["status"] == "inserted"
    assert result["key"].startswith("customer:")


@pytest.mark.asyncio
async def test_insert_redis_json():
    client = PolyClient(options={"data_type": "json"})
    sql = "INSERT INTO customer (id, name) VALUES ('3', 'RedisJsonUser')"
    result = await client.insert(sql, engine="redis")
    assert result["status"] == "inserted"
    assert result["key"].startswith("customer:")
