import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_delete_from_redis():
    """
    Tests that a record can be inserted and then deleted from Redis
    using the catalogue for routing.
    """
    async with PolyClient(options={"data_type": "string"}) as client:
        # Arrange: Insert a unique customer.
        customer_id = "DEL-RD-" + str(uuid.uuid4())[:4]
        company_name = "Redis Company To Delete"

        # The catalogue maps 'customers' to Redis, so we use use_catalogue=True
        insert_sql = (
            f"INSERT INTO Customer (ID, companyName) "
            f"VALUES ('{customer_id}', '{company_name}')"
        )
        await client.execute(insert_sql, engine="redis")

        # Confirm it exists before deleting
        doc = await client.get("Customer", customer_id, "redis")
        print("test-delete-from-redis-doc", doc)
        assert doc["companyName"] == company_name

        # Act: Delete the record using the catalogue.
        delete_sql = f"DELETE FROM Customer WHERE customerID = '{customer_id}'"
        delete_result = await client.execute(delete_sql, engine="redis")

        # Assert: The connector should report at least one key was deleted.
        assert delete_result["deleted_count"] >= 1

        # Assert: Verify the record is gone by trying to get it again.
        deleted_doc = await client.get("Customer", customer_id, "redis")
        msg = "The record should have been deleted, but was found."
        assert not deleted_doc, msg
