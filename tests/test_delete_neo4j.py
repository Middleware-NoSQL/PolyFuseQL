import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_delete_from_neo4j():
    """
    Tests that a node can be created and then deleted from Neo4j.
    """
    async with PolyClient() as client:
        # Arrange: Insert a new Person node to delete.
        person_id = "DEL-NJ-" + str(uuid.uuid4())[:4]
        person_name = "Person to Delete"

        # The catalogue maps 'person' to Neo4j.
        insert_sql = "INSERT INTO Person (id, name) "
        insert_sql += f"VALUES ('{person_id}', '{person_name}')"  # noqa: F501
        insert_result = await client.execute(insert_sql, engine="neo4j")
        assert insert_result["id"] == person_id

        # Confirm it exists before deleting.
        doc = await client.get("person", person_id)
        assert doc["name"] == person_name

        # Act: Delete the node.
        delete_sql = f"DELETE FROM Person WHERE id = '{person_id}'"
        delete_result = await client.execute(delete_sql, engine="neo4j")

        # Assert: The connector should report 1 node deleted.
        assert delete_result["deleted_count"] == 1

        # Assert: Verify the node is gone.
        deleted_doc = await client.get("person", person_id)
        msg = "The node should have been deleted, but was found."
        assert not deleted_doc, msg
