import pytest
import uuid
from cassandra.cluster import Cluster
from polyfuseql.client import PolyClient
from polyfuseql.config import settings

# --- Test Data and Schema ---
TEST_KEYSPACE = "mykeyspace"  # Must match what the translator expects
TEST_TABLE = "test_integration_users"


def setup_cassandra_schema():
    """
    Connects directly to Cassandra to create the necessary keyspace and table
    for testing. This is a blocking operation run once per module.
    """
    try:
        cluster = Cluster(
            [settings.cassandra.host], port=settings.cassandra.port
        )  # noqa:E501
        session = cluster.connect()
        session.execute(
            f"""
            CREATE KEYSPACE IF NOT EXISTS {TEST_KEYSPACE}
            WITH REPLICATION = {{ 'class': 'SimpleStrategy', 'replication_factor': 1 }}
            """  # noqa:E501
        )
        session.set_keyspace(TEST_KEYSPACE)
        session.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
                user_id int PRIMARY KEY,
                name text,
                email text,
                age int
            )
            """
        )
        # Clean the table before tests start
        session.execute(f"TRUNCATE TABLE {TEST_TABLE}")
        cluster.shutdown()
    except Exception as e:
        pytest.fail(f"Failed to set up Cassandra schema: {e}")


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Module-level fixture to set up the database schema once."""
    setup_cassandra_schema()


@pytest.fixture(scope="module")
def event_loop():
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_cassandra_crud_operations():
    """Tests the full Create, Read, Update, Delete cycle using PolyClient."""
    async with PolyClient() as client:
        # Arrange: Use a unique ID for this test case
        user_id = int(str(uuid.uuid4().int)[:5])
        original_name = "Cassandra User"
        updated_name = "Updated Cassandra User"

        # 1. Insert (Create)
        insert_sql = (
            f"INSERT INTO {TEST_TABLE} (user_id, name, email, age) "
            f"VALUES ({user_id}, '{original_name}', 'crud@example.com', 40)"
        )
        # Execute returns None for successful inserts via this path
        await client.execute(insert_sql, engine="cassandra")

        # 2. Get (Read)
        user = await client.get(TEST_TABLE, user_id, engine="cassandra")
        assert user is not None
        assert user["name"] == original_name
        assert user["age"] == 40

        # 3. Update
        update_sql = f"UPDATE {TEST_TABLE} SET name = '{updated_name}' WHERE user_id = {user_id}"  # noqa:E501
        update_result = await client.execute(update_sql, engine="cassandra")
        assert update_result["updated_count"] == 1

        # Verify Update
        updated_user = await client.get(
            TEST_TABLE, user_id, engine="cassandra"
        )  # noqa:E501
        assert updated_user is not None
        assert updated_user["name"] == updated_name

        # 4. Delete
        delete_sql = f"DELETE FROM {TEST_TABLE} WHERE user_id = {user_id}"
        delete_result = await client.execute(delete_sql, engine="cassandra")
        assert delete_result["deleted_count"] == 1

        # Verify Deletion
        deleted_user = await client.get(
            TEST_TABLE, user_id, engine="cassandra"
        )  # noqa:E501
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
        # The test assumes at least these two users exist;
        # could be more from other tests
        assert len(all_users) >= 2

        # Act & Assert: count
        count_result = await client.execute(
            f"SELECT COUNT(*) FROM {TEST_TABLE}", engine="cassandra"
        )
        assert count_result[0]["count"] >= 2


@pytest.mark.asyncio
async def test_cassandra_complex_query():
    """Tests a SELECT with a WHERE clause via PolyClient."""
    async with PolyClient() as client:
        # Arrange
        user_id = int(str(uuid.uuid4().int)[:7])
        await client.execute(
            f"INSERT INTO {TEST_TABLE} (user_id, name, age, email) VALUES ({user_id}, 'FilterUser', 55, 'filter@example.com')",  # noqa:E501
            engine="cassandra",
        )

        # Act: Execute a query that requires translation and filtering
        sql = f"SELECT name, email FROM {TEST_TABLE} WHERE age > 50"
        results = await client.execute(sql, engine="cassandra")

        # Assert
        assert any(r["name"] == "FilterUser" for r in results)
        record = next((r for r in results if r["name"] == "FilterUser"), None)
        assert record is not None
        assert "age" not in record
        assert record["email"] == "filter@example.com"
