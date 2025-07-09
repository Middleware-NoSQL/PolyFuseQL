import logging

import pytest
from polyfuseql.client.PolyClient import PolyClient
import uuid


@pytest.mark.asyncio
async def test_postgres_group_by():
    """Tests a native GROUP BY query in PostgreSQL."""
    async with PolyClient() as client:
        # This query counts how many customers are in each country.
        sql = 'SELECT "country", COUNT(*) AS customercount '
        sql += 'FROM customers GROUP BY "country"'
        results = await client.execute(sql, engine="postgres")

        assert len(results) > 1
        # Find the result for USA and check its count
        usa_result = next(
            (item for item in results if item["country"] == "USA"), None
        )  # noqa: F501
        assert usa_result is not None
        logging.info("test_postgres_group_by-usa_result", usa_result)
        assert usa_result["customercount"] > 5


@pytest.mark.asyncio
async def test_neo4j_group_by():
    """Tests a SQL GROUP BY translated to Cypher."""
    async with PolyClient() as client:
        sql = "SELECT country, COUNT(*) AS customer_count "
        sql += "FROM Customer GROUP BY country"
        results = await client.execute(sql, engine="neo4j")

        assert len(results) > 1
        usa_result = next(
            (item for item in results if item["country"] == "USA"), None
        )  # noqa: F501
        assert usa_result is not None
        logging.info("test_neo4j_group_by-usa_result", usa_result)
        assert usa_result["customer_count"] > 5


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_redis_application_side_group_by():
    """
    Tests an application-side GROUP BY on data in Redis,
    ensuring test data is cleaned up afterward.
    """
    # Use the 'user' namespace which is mapped to Redis in the catalogue
    namespace = "user"

    # We will insert and later delete these specific users
    test_data = [
        {"id": str(uuid.uuid4()), "city": "Paris"},
        {"id": str(uuid.uuid4()), "city": "London"},
        {"id": str(uuid.uuid4()), "city": "Paris"},
        {"id": str(uuid.uuid4()), "city": "Tokyo"},
        {"id": str(uuid.uuid4()), "city": "Paris"},
    ]

    # The client options reflect that 'id' is
    # the primary key for the 'user' table.
    async with PolyClient(options={"pk": "id"}) as client:
        try:
            # Arrange: Insert test data using SQL INSERT statements.
            for item in test_data:
                item_id = item["id"]
                item_city = item["city"]
                sql = f"INSERT INTO {namespace} (id, city) "
                sql += f"VALUES ('{item_id}', '{item_city}')"

                await client.execute(sql, engine="redis")

            # Act: Perform the GROUP BY query.
            sql = "SELECT city, COUNT(*) as city_count "
            sql += f"FROM {namespace} GROUP BY city"
            results = await client.execute(sql, engine="redis")

            # Assert: Check the aggregation results.
            assert len(results) == 3
            results.sort(key=lambda x: x["city"])

            assert results[0] == {"city": "London", "city_count": 1}
            assert results[1] == {"city": "Paris", "city_count": 3}
            assert results[2] == {"city": "Tokyo", "city_count": 1}

        finally:
            # Cleanup: Delete all records created during the test.
            print("\n--- Cleaning up test data from Redis ---")
            for item in test_data:
                item_id = item["id"]
                sql = f"DELETE FROM {namespace} WHERE id = '{item_id}'"
                delete_result = await client.execute(sql, engine="redis")
                print(f"Deleted user {item_id}: {delete_result}")
