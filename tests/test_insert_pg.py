import uuid

import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_insert_postgres():
    async with PolyClient() as client:
        # Generate a unique ID to avoid UniqueViolationError on reruns
        customer_id = str(uuid.uuid4())[:5]
        company_name = "New PG Co"
        print("customer_id", customer_id)
        print("company_name", company_name)

        # Use CamelCase to match Python code, connector will handle snake_case
        sql = "INSERT INTO customers (customer_id, company_name) "
        sql += f"VALUES ('{customer_id}', '{company_name}')"  # noqa: F501

        result = await client.execute(sql, engine="postgres")
        print(result.keys())
        assert result["customerId"] == customer_id
        assert result["companyName"] == company_name
