import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
@pytest.mark.parametrize("data_type", ["string", "hash", "json"])
async def test_update_redis(data_type):
    """Tests that a record can be updated in Redis for all data types."""
    async with PolyClient(options={"data_type": data_type}) as client:
        # Arrange
        customer_id = f"UPD-RD{str(uuid.uuid4())[:5]}"
        original_name = "Original Redis Co"
        updated_name = "Updated Redis Co"

        sql = "INSERT INTO Customer (id, name) "
        sql += f"VALUES ('{customer_id}', '{original_name}')"
        result = await client.execute(sql, engine="redis")
        assert result["status"] == "inserted"
        assert result["key"] == f"Customer:{customer_id}"

        # Act: Update using an SQL statement
        update_sql = (
            f"UPDATE Customer SET companyName = '{updated_name}' "
            f"WHERE customer_id = '{customer_id}'"
        )
        result = await client.execute(update_sql, engine="redis")
        assert result["updated_count"] == 1

        # Assert
        doc = await client.get("Customer", customer_id, engine="redis")
        assert doc is not None
        assert doc["companyName"] == updated_name
