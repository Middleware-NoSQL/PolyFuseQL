import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_update_neo4j():
    """Tests that a node's properties can be updated in Neo4j."""
    async with PolyClient() as client:
        # Arrange
        person_id = "UPD-NJ-" + str(uuid.uuid4())[:4]
        original_name = "Original Person"
        updated_name = "Updated Person Name"

        insert_sql = (
            f"INSERT INTO Person (id, name) "
            f"VALUES ('{person_id}', '{original_name}')"
        )
        await client.execute(insert_sql, engine="neo4j")

        # Act
        update_sql = f"UPDATE Person SET name = '{updated_name}' "
        update_sql += f"WHERE id = '{person_id}'"
        result = await client.execute(update_sql, engine="neo4j")

        # Assert: properties_set returns the number of properties changed.
        assert result["updated_count"] > 0

        # Assert: Verify the data was changed.
        doc = await client.get("person", person_id)
        assert doc["name"] == updated_name
