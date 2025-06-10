import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_postgres():
    """
    Tests that a new record can be
    inserted into the PostgreSQL 'Customer' table.
    """
    client = PolyClient()
    customer_id = "NEWPG"
    company_name = "New PG Co"

    sql = 'INSERT INTO customers ("customer_id", "company_name")'
    sql += f"VALUES ('{customer_id}', '{company_name}')"
    # Use the new execute method which leverages the InsertStrategy
    result = await client.execute(sql, engine="postgres")
    print(result.keys())
    assert result["customerId"] == customer_id
    assert result["companyName"] == company_name

    # Optional: Verify with a SELECT query
    rows = await client.execute(
        f"SELECT * FROM customers WHERE \"customer_id\" = '{customer_id}'",
        engine="postgres",
    )
    assert rows
    assert rows[0]["companyName"] == company_name
