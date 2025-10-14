import logging

import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient

# --- Test Constants ---
TEST_KEYSPACE = "mykeyspace"
TEST_TABLE = "test_integration_users"


@pytest.fixture(scope="module", autouse=True)
async def setup_test_schema():
    """
    Pytest fixture to ensure the required keyspace and table exist before
    any tests in this module are run. It performs setup by calling the
    translator API itself, guaranteeing that the schema is created in the
    correct database instance that the service is connected to.
    """
    print("\n--- [Module Setup] Ensuring Cassandra schema exists via API ---")
    # create_keyspace_sql = f"""
    # CREATE KEYSPACE IF NOT EXISTS {TEST_KEYSPACE}
    # WITH REPLICATION = {{ 'class': 'SimpleStrategy',
    # 'replication_factor': 1 }}
    # """
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {TEST_KEYSPACE}.{TEST_TABLE} (
        user_id int PRIMARY KEY,
        name text,
        email text,
        age int
    )
    """
    async with PolyClient() as client:
        # We don't need to specify the keyspace for creating a keyspace
        # await client.execute(create_keyspace_sql, engine="cassandra")
        # print(f"-> Ensured keyspace '{TEST_KEYSPACE}' exists.")

        # Now execute the CREATE TABLE statement
        await client.execute(create_table_sql, engine="cassandra")
        print(f"-> Ensured table '{TEST_TABLE}' exists.")
    print("--- [Module Setup] Schema setup complete ---")


@pytest.fixture(scope="function", autouse=True)
async def clean_test_table():
    """
    Pytest fixture that runs before each test function. It truncates the test
    table to ensure that each test starts with a clean slate and is independent
    of others.
    """
    truncate_sql = f"TRUNCATE TABLE {TEST_KEYSPACE}.{TEST_TABLE}"
    async with PolyClient() as client:
        await client.execute(truncate_sql, engine="cassandra")


@pytest.mark.asyncio
async def test_cassandra_crud_operations():
    """Tests the full Create, Read, Update, Delete cycle using PolyClient."""
    async with PolyClient() as client:
        user_id = int(str(uuid.uuid4().int)[:5])
        original_name = "Cassandra User"
        updated_name = "Updated Cassandra User"

        # 1. Insert (Create)
        insert_sql = (
            f"INSERT INTO {TEST_TABLE} (user_id, name, email, age) "
            f"VALUES ({user_id}, '{original_name}', 'crud@example.com', 40)"
        )
        insert_result = await client.execute(insert_sql, engine="cassandra")
        assert insert_result == []

        # 2. Get (Read)
        user = await client.get(
            TEST_TABLE,
            primary_key_value=user_id,
            engine="cassandra",
            primary_key_column="user_id",
        )
        assert user is not None
        assert user["name"] == original_name
        assert user["age"] == 40

        # 3. Update
        update_sql = f"UPDATE {TEST_TABLE} SET name = '{updated_name}' WHERE user_id = {user_id}"  # noqa:E501
        update_result = await client.execute(
            update_sql, engine="cassandra", use_catalogue=False
        )
        assert update_result == {"backend": "cassandra", "updated_count": 1}

        # Verify Update
        updated_user = await client.get(
            TEST_TABLE,
            primary_key_value=user_id,
            engine="cassandra",
            primary_key_column="user_id",
        )
        assert updated_user is not None
        assert updated_user["name"] == updated_name

        # 4. Delete
        delete_sql = f"DELETE FROM {TEST_TABLE} WHERE user_id = {user_id}"
        delete_result = await client.execute(
            delete_sql, engine="cassandra", use_catalogue=False
        )
        assert delete_result == {"backend": "cassandra", "deleted_count": 1}

        # Verify Deletion
        deleted_user = await client.get(
            TEST_TABLE,
            primary_key_value=user_id,
            engine="cassandra",
            primary_key_column="user_id",
        )
        assert deleted_user is None


@pytest.mark.asyncio
async def test_cassandra_get_all_and_count():
    """Tests fetching all records and counting them via PolyClient."""
    async with PolyClient() as client:
        # Arrange: Insert known data
        user_id_1 = int(str(uuid.uuid4().int)[:5])
        user_id_2 = int(str(uuid.uuid4().int)[:6])
        await client.execute(
            f"INSERT INTO {TEST_TABLE} (user_id, name, age) VALUES ({user_id_1}, 'User A', 30)",  # noqa:E501
            engine="cassandra",
        )
        await client.execute(
            f"INSERT INTO {TEST_TABLE} (user_id, name, age) VALUES ({user_id_2}, 'User B', 35)",  # noqa:E501
            engine="cassandra",
        )

        # Act & Assert: get_all (by executing SELECT *)
        all_users = await client.execute(
            f"SELECT * FROM {TEST_TABLE}", engine="cassandra"
        )
        assert len(all_users) >= 2

        # Act & Assert: count
        count_result = await client.execute(
            f"SELECT COUNT(*) FROM {TEST_TABLE}", engine="cassandra"
        )
        assert count_result and "count" in count_result[0]
        logging.info(f"count_result: {count_result}")
        assert int(count_result[0]["count"]) >= 2


@pytest.mark.asyncio
async def test_cassandra_complex_query():
    """Tests a SELECT with a WHERE clause that requires filtering."""
    async with PolyClient() as client:
        # Arrange
        user_id = int(str(uuid.uuid4().int)[:7])
        await client.execute(
            f"INSERT INTO {TEST_TABLE} (user_id, name, age, email) VALUES ({user_id}, 'FilterUser', 55, 'filter@example.com')",  # noqa:E501
            engine="cassandra",
        )

        # Act: Execute a query that requires translation and filtering.
        sql = f"SELECT name, email FROM {TEST_TABLE} WHERE age > 50"
        results = await client.execute(sql, engine="cassandra")
        logging.info(f"results: {results}")
        # Assert
        assert any(r["name"] == "FilterUser" for r in results)
        record = next((r for r in results if r["name"] == "FilterUser"), None)
        assert record is not None
        assert "age" not in record
        assert record["email"] == "filter@example.com"
