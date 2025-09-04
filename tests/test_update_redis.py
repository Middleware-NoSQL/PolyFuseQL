import logging

import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
@pytest.mark.parametrize("data_type", ["string", "hash", "json"])
async def test_update_redis(data_type):
    """Tests that a record can be updated in Redis
    for all supported data types."""
    # The PolyClient now accepts an 'options' dict to specify behavior.
    async with PolyClient(options={"data_type": data_type}) as client:
        # Arrange
        customer_id = f"UPD-RD-{str(uuid.uuid4())[:5]}"
        original_name = "Original Redis Co"
        updated_name = "Updated Redis Co"

        # The test relies on the catalogue to route 'Customer' to Redis.
        insert_sql = (
            f"INSERT INTO customer (c_custkey, companyName) "
            f"VALUES ('{customer_id}', '{original_name}')"
        )
        await client.execute(insert_sql, engine="redis")

        # Act: Update using a standard SQL statement.
        update_sql = (
            f"UPDATE customer SET companyName = '{updated_name}' "
            f"WHERE c_custkey = '{customer_id}'"
        )
        result = await client.execute(update_sql, engine="redis")
        logging.info(f"result {result}")
        assert result["updated_count"] == 1

        # Assert: Verify the data was changed.
        doc = await client.get("customer", customer_id, engine="redis")
        logging.info(f"doc {doc}")
        assert doc is not None
        assert doc["companyName"] == updated_name
