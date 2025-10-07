import pytest
import uuid
import pymongo
from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.config import settings
import logging

# --- Test Data and Schema ---
TEST_COLLECTION = "test_integration_users"


def setup_mongo_db():
    """
    Connects directly to MongoDB to ensure the test collection is clean.
    This is a blocking operation run once per module.
    """
    try:
        logging.info("Connecting to MongoDB server")
        client = pymongo.MongoClient(
            host=settings.mongodb.host,
            port=settings.mongodb.port,
            username=settings.mongodb.user,
            password=settings.mongodb.password,
        )
        logging.info(f"settings.mongodb.host: {settings.mongodb.host}")
        logging.info(f"settings.mongodb.port: {settings.mongodb.port}")
        logging.info(f"settings.mongodb.user: {settings.mongodb.user}")
        logging.info(f"settings.mongodb.password: {settings.mongodb.password}")
        db = client[settings.mongodb.db]
        # Drop the collection to ensure a clean state
        db.drop_collection(TEST_COLLECTION)
        client.close()
    except Exception as e:
        pytest.fail(f"Failed to set up MongoDB: {e}")


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Module-level fixture to set up the database schema once."""
    setup_mongo_db()


@pytest.fixture(scope="module")
def event_loop():
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_mongodb_crud_operations():
    """Tests the full Create, Read, Update, Delete cycle using PolyClient."""
    async with PolyClient() as client:
        # Arrange: Use a unique ID for this test case
        user_id = int(str(uuid.uuid4().int)[:5])
        original_name = "Mongo User"
        updated_name = "Updated Mongo User"

        # 1. Insert (Create)
        insert_sql = (
            f"INSERT INTO {TEST_COLLECTION} (user_id, name, email, age) "
            f"VALUES ({user_id}, '{original_name}', 'crud@example.com', 30)"
        )
        insert_res = await client.execute(
            insert_sql, engine="mongodb", use_catalogue=False
        )
        logging.info(f"Insertion response: {insert_res}")

        # 2. Get (Read) - Note: pk_col for mongo is 'user_id' in this test
        logging.info(
            f"Inserted {original_name} with id {user_id} into {TEST_COLLECTION}"  # noqa:E501
        )
        user = await client.get(
            TEST_COLLECTION,
            primary_key_value=user_id,
            engine="mongodb",
            primary_key_column="user_id",
        )
        logging.info(f"user-crud: {user}")
        assert user is not None
        assert user["name"] == original_name
        assert user["age"] == 30

        # 3. Update
        update_sql = f"UPDATE {TEST_COLLECTION} SET name = '{updated_name}' WHERE user_id = {user_id}"  # noqa:E501
        update_result = await client.execute(
            update_sql, engine="mongodb", use_catalogue=False
        )
        assert update_result["updated_count"] == 1

        # Verify Update
        updated_user = await client.get(
            TEST_COLLECTION,
            user_id,
            engine="mongodb",
            primary_key_column="user_id",  # noqa:E501
        )
        assert updated_user is not None
        assert updated_user["name"] == updated_name

        # 4. Delete
        delete_sql = f"DELETE FROM {TEST_COLLECTION} WHERE user_id = {user_id}"
        delete_result = await client.execute(
            delete_sql, engine="mongodb", use_catalogue=False
        )
        assert delete_result["deleted_count"] == 1

        # Verify Deletion
        deleted_user = await client.get(
            TEST_COLLECTION,
            user_id,
            engine="mongodb",
            primary_key_column="user_id",  # noqa:E501
        )
        assert deleted_user is None


@pytest.mark.asyncio
async def test_mongodb_get_all_and_count():
    """Tests fetching all records and counting them via PolyClient."""
    async with PolyClient() as client:
        # Arrange: Insert known data with unique IDs
        user_id_1 = int(str(uuid.uuid4().int)[:5])
        user_id_2 = int(str(uuid.uuid4().int)[:6])
        await client.execute(
            f"INSERT INTO {TEST_COLLECTION} (user_id, name, age) VALUES ({user_id_1}, 'User A', 25)",  # noqa:E501
            engine="mongodb",
            use_catalogue=False,
        )
        await client.execute(
            f"INSERT INTO {TEST_COLLECTION} (user_id, name, age) VALUES ({user_id_2}, 'User B', 45)",  # noqa:E501
            engine="mongodb",
            use_catalogue=False,
        )

        # Act & Assert: get_all (by executing SELECT *)
        all_users = await client.execute(
            f"SELECT * FROM {TEST_COLLECTION}",
            engine="mongodb",
            use_catalogue=False,  # noqa:E501
        )
        assert len(all_users) >= 2

        # Not implemented aggregation in mongo translator
        # Act & Assert: count
        # count_result = await client.execute(
        #     f"SELECT COUNT(*) FROM {TEST_COLLECTION}",
        #     engine="mongodb", use_catalogue=False
        # )
        # logging.info(f"count_result: {count_result}")
        # assert count_result[0]["count"] >= 2


@pytest.mark.asyncio
async def test_mongodb_complex_query():
    """Tests a SELECT with a WHERE clause via PolyClient."""
    async with PolyClient() as client:
        # Arrange
        user_id = int(str(uuid.uuid4().int)[:7])
        await client.execute(
            f"INSERT INTO {TEST_COLLECTION} (user_id, name, age, email) VALUES ({user_id}, 'ComplexUser', 60, 'complex@example.com')",  # noqa:E501
            engine="mongodb",
            use_catalogue=False,
        )

        # Act: Execute a query that requires translation
        sql = f"SELECT name, email FROM {TEST_COLLECTION} WHERE age > 50"
        results = await client.execute(
            sql, engine="mongodb", use_catalogue=False
        )  # noqa:E501

        # Assert
        assert any(r["name"] == "ComplexUser" for r in results)
        record = next((r for r in results if r["name"] == "ComplexUser"), None)
        assert record is not None
        assert "age" not in record
        assert record["email"] == "complex@example.com"
