import pytest
from polyfuseql.client.PolyClient import PolyClient

# We will test INSERT on the TPC-H 'region' table,
# which is mapped to Postgres in schemas.json.

REGION_ID = 99
REGION_NAME = "Test Region"


@pytest.mark.asyncio
async def test_insert_postgres():
    async with PolyClient() as client:
        # Use column names as defined in schemas.json
        sql = "INSERT INTO region (r_regionkey, r_name) "
        sql += f"VALUES ({REGION_ID}, '{REGION_NAME}')"

        result = await client.execute(
            sql, engine="postgres", use_catalogue=True
        )  # noqa:E501
        assert result["rRegionkey"] == REGION_ID
        assert result["rName"].strip() == REGION_NAME

        # Cleanup
        await client.execute(
            f"DELETE FROM region WHERE r_regionkey = {REGION_ID}",
            engine="postgres",
        )
