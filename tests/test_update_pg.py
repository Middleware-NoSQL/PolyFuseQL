import pytest
from polyfuseql.client.PolyClient import PolyClient

# We will test UPDATE on the TPC-H 'region' table.
REGION_ID = 101
ORIGINAL_NAME = "Original Region"
UPDATED_NAME = "Updated Region Name"


@pytest.mark.asyncio
async def test_update_postgres():
    """Tests that a TPC-H record can be updated in PostgreSQL."""
    async with PolyClient() as client:
        # Arrange: Insert a new region to update.
        insert_sql = (
            f"INSERT INTO region (r_regionkey, r_name) "
            f"VALUES ({REGION_ID}, '{ORIGINAL_NAME}')"
        )
        await client.execute(insert_sql, engine="postgres")

        # Act: Update the record.
        update_sql = (
            f"UPDATE region SET r_name = '{UPDATED_NAME}' "
            f"WHERE r_regionkey = {REGION_ID}"
        )
        result = await client.execute(update_sql, engine="postgres")
        assert result["updated_count"] == 1

        # Assert: Fetch the record and verify the change.
        doc = await client.get(
            "region",
            REGION_ID,
            primary_key_column="r_regionkey",
            engine="postgres",
        )
        assert doc["rName"].strip() == UPDATED_NAME

        # Cleanup
        await client.execute(
            f"DELETE FROM region WHERE r_regionkey = {REGION_ID}",
            engine="postgres",
        )
