import pytest

from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_neo4j():
    client = PolyClient()
    sql = "INSERT INTO Person (id, name) VALUES ('123', 'Neo4jUser')"
    result = await client.query(sql, engine="neo4j")
    assert result.get("id") == "123"
    assert result.get("name") == "Neo4jUser"
