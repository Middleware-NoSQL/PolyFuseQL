from decimal import Decimal

import pytest
import pytest_asyncio
from pathlib import Path
from polyfuseql.client.PolyClient import PolyClient
import uuid

# Define the path to the fixture file
FIXTURE_DIR = Path(__file__).parent / "fixtures"
NATION_FIXTURE = FIXTURE_DIR / "nation.tbl"
REGION_FIXTURE = FIXTURE_DIR / "region.tbl"


@pytest_asyncio.fixture(scope="function")
async def postgres_join_data():
    """
    Fixture to load only the data needed for the native postgres join test.
    """
    if not NATION_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {NATION_FIXTURE}")
    if not REGION_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {REGION_FIXTURE}")

    print("\n--- Populating databases for test_native_postgres_join ---")
    async with PolyClient() as client:
        # Load data into PostgreSQL
        r_count = await client.bulk_load_table(
            "region", str(REGION_FIXTURE), "postgres"
        )
        print(f"Loaded {r_count} records into Postgres (region).")

        n_count = await client.bulk_load_table(
            "nation", str(NATION_FIXTURE), "postgres"
        )
        print(f"Loaded {n_count} records into Postgres (nation).")
    print("--- Database population complete ---")
    yield
    # Cleanup if necessary, though bulk_load_table truncates
    print("--- Postgres data teardown ---")


@pytest.mark.asyncio
@pytest.mark.usefixtures("postgres_join_data")
async def test_native_postgres_join():
    """
    Tests a native JOIN on two TPC-H tables (nation and region)
    within PostgreSQL.
    """
    async with PolyClient() as client:
        # Both 'nation' and 'region' are on postgres per schemas.json
        sql = """
              SELECT n.n_name, r.r_name
              FROM nation AS n
              JOIN region AS r ON n.n_regionkey = r.r_regionkey
              WHERE n.n_nationkey = 1
              """
        results = await client.execute(sql, engine="postgres")
        assert len(results) == 1
        assert results[0]["nName"].strip() == "ARGENTINA"
        assert results[0]["rName"].strip() == "AMERICA"


@pytest.mark.asyncio
async def test_redis_application_side_join():
    """
    Tests an application-side JOIN between two synthetic Redis namespaces
    ('customer_redis' and 'orders_redis'), which are defined in schemas.json.
    This test uses INSERTs, not .tbl files.
    """
    async with PolyClient(options={"data_type": "string"}) as client:
        # Arrange: Insert data into 'customer_redis' and 'orders_redis'
        cust_id = "join-cust-" + str(uuid.uuid4())[:4]
        order_id = "join-ord-" + str(uuid.uuid4())[:4]

        # Use the new tables defined in schemas.json
        cust_sql = "INSERT INTO customer_redis (c_custkey, c_name) "
        cust_sql += f"VALUES ('{cust_id}', 'John Doe')"

        order_sql = "INSERT INTO orders_redis "
        order_sql += "(o_orderkey, o_custkey, o_totalprice) "
        order_sql += f"VALUES ('{order_id}', '{cust_id}', 120.50)"

        await client.execute(cust_sql, engine="redis")
        await client.execute(order_sql, engine="redis")

        # Act: Perform the JOIN
        # Use the new tables in the SELECT query
        sql = f"""
              SELECT customer_redis.c_name, orders_redis.o_totalprice
              FROM customer_redis
              JOIN orders_redis
              ON customer_redis.c_custkey = orders_redis.o_custkey
              WHERE customer_redis.c_custkey = '{cust_id}'
              """
        results = await client.execute(sql, engine="redis")

        # Assert
        assert len(results) == 1
        assert results[0]["cName"] == "John Doe"
        # Note: Redis connector stringifies everything
        assert results[0]["oTotalprice"] == Decimal("120.5000")
