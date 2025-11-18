import pytest
from polyfuseql.client.PolyClient import PolyClient

# We will test DELETE on the TPC-H 'region' table.
REGION_ID = 100
REGION_NAME = "RegionToDelete"


@pytest.mark.asyncio
async def test_delete_from_postgres():
    """
    Tests that a TPC-H record can be inserted and then deleted from PostgreSQL.
    """
    async with PolyClient() as client:
        # Arrange: Insert a new region to delete.
        insert_sql = (
            f"INSERT INTO region (r_regionkey, r_name) "
            f"VALUES ({REGION_ID}, '{REGION_NAME}')"
        )
        await client.execute(insert_sql, engine="postgres")

        # Act: Execute the DELETE statement.
        delete_sql = f"DELETE FROM region WHERE r_regionkey = {REGION_ID}"
        delete_result = await client.execute(delete_sql, engine="postgres")

        # Assert: Check that one record was reported as deleted.
        assert delete_result["deleted_count"] == 1

        # Assert: Verify the record is gone.
        deleted_doc = await client.get(
            "region",
            REGION_ID,
            primary_key_column="r_regionkey",
            engine="postgres",
        )
        msg = "The record should have been deleted, but was found."
        assert not deleted_doc, msg
