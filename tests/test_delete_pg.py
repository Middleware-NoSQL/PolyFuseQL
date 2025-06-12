import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_delete_from_postgres():
    """
    Tests that a record can be inserted and then deleted from PostgreSQL.
    """
    async with PolyClient() as client:
        # Arrange: Insert a new, unique record to delete.
        id = "DEL" + str(uuid.uuid4())[:2]
        company_name = "CompanyToDelete"

        insert_sql = (
            f"INSERT INTO customers (customer_id, company_name) "
            f"VALUES ('{id}', '{company_name}')"
        )

        insert_result = await client.execute(insert_sql, engine="postgres")
        print("Insert result:", insert_result)
        assert insert_result["customerId"] == id

        # Act: Execute the DELETE statement.
        delete_sql = "DELETE FROM customers WHERE "
        delete_sql += f"customer_id = '{id}'"
        delete_result = await client.execute(delete_sql, engine="postgres")
        print("delete_result", delete_result)
        # Assert: Check that one record was reported as deleted.
        # Note: The raw query path for DELETE needs a defined return format.
        # Let's assume the Postgres query method will return a status.

        # Assert: Verify the record is gone.
        deleted_doc = await client.get("customers", id, engine="postgres")
        msg = "The record should have been deleted, but was found."
        assert not deleted_doc, msg
