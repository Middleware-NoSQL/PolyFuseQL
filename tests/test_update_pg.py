import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_update_postgres():
    """Tests that a record can be updated in PostgreSQL."""
    async with PolyClient() as client:
        # Arrange: Insert a new customer to update.
        customer_id = "U" + str(uuid.uuid4())[:4]
        original_name = "Original Company"
        updated_name = "Updated Company Name"

        insert_sql = (
            f"INSERT INTO customers (customer_id, company_name) "
            f"VALUES ('{customer_id}', '{original_name}')"
        )
        await client.execute(insert_sql, engine="postgres")

        # Act: Update the record.
        update_sql = (
            f"UPDATE customers SET company_name = '{updated_name}' "
            f"WHERE customer_id = '{customer_id}'"
        )
        result = await client.execute(update_sql, engine="postgres")
        assert result["updated_count"] == 1

        # Assert: Fetch the record and verify the change.
        doc = await client.get("customers", customer_id, engine="postgres")
        assert doc["companyName"] == updated_name
