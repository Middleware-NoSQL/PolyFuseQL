import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_neo4j():
    """
    Tests that a new node can be inserted into the Neo4j database.
    """
    async with PolyClient() as client:
        sql = "INSERT INTO Person (id, name) VALUES ('123', 'Neo4jUser')"

        # Use the execute method for consistency
        result = await client.execute(sql, engine="neo4j")

        assert result.get("id") == "123"
        assert result.get("name") == "Neo4jUser"

        # Verify with a SELECT query
        sql = "SELECT * FROM Person WHERE id = '123'"
        rows = await client.execute(sql, engine="neo4j")
        assert rows
        assert rows[0]["name"] == "Neo4jUser"
