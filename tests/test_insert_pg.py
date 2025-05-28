import pytest

from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_postgres():
    client = PolyClient()
    sql = "INSERT INTO customers (customer_id, company_name)"
    sql = sql + " VALUES ('NEWID', 'New Co')"
    result = await client.query(sql, engine="postgres")
    assert result["customer_id"] == "NEWID"
    assert result["company_name"] == "New Co"
