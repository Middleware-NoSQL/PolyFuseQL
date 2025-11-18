import logging

import pytest
import pytest_asyncio  # Import pytest_asyncio
from pathlib import Path  # Import Path
from polyfuseql.client.PolyClient import PolyClient

# This test now queries the TPC-H 'customer' table.
# We will use c_custkey = 1, which corresponds to 'Customer#000000001'
# in the TPC-H fixtures.

CUSTOMER_ID = 1
EXPECTED_NAME = "Customer#000000001"

# Define the path to the fixture file
FIXTURE_DIR = Path(__file__).parent / "fixtures"
CUSTOMER_FIXTURE = FIXTURE_DIR / "customer.tbl"

DATABASE_TYPE = "ALL"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def populate_databases(database_type: str = DATABASE_TYPE):
    """
    Module-scoped fixture to load customer data into Postgres and Neo4j
    before tests run.
    """
    if not CUSTOMER_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {CUSTOMER_FIXTURE}")

    print("\n--- Populating databases for test_get_customer ---")
    async with PolyClient() as client:
        # Load data into PostgreSQL
        if database_type == "PostgreSQL" or database_type == "ALL":
            pg_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "postgres"
            )
            print(f"Loaded {pg_count} records into Postgres.")
        if database_type == "Neo4j" or database_type == "ALL":
            # Load data into Neo4j
            nj_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "neo4j"
            )
            print(f"Loaded {nj_count} records into Neo4j.")
        if database_type == "Redis" or database_type == "ALL":
            # Load data into Neo4j
            rd_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis.")

        if database_type == "Redis_Hash" or database_type == "ALL":
            # Load data into Redis
            client.options = {
                "data_type": "hash",
                "include_data_type_in_pk": True,
            }  # noqa:E501
            rd_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis.")
        if database_type == "Redis_Json" or database_type == "ALL":
            # Load data into Redis
            client.options = {
                "data_type": "json",
                "include_data_type_in_pk": True,
            }  # noqa:E501
            rd_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis.")
    print("--- Database population complete ---")


@pytest.mark.asyncio
async def test_get_customer_postgres():
    """
    Tests getting a TPC-H customer from PostgreSQL.
    Note: schemas.json maps 'customer' to neo4j, so we must
    override the engine to 'postgres' for this test.
    """
    async with PolyClient() as c:
        # We query 'customer' table (TPC-H) not 'customers' (Northwind)
        # We specify engine='postgres' to override the catalogue.
        doc = await c.get(
            "customer",
            CUSTOMER_ID,
            primary_key_column="c_custkey",
            engine="postgres",
        )
        assert doc["cName"] == EXPECTED_NAME


@pytest.mark.asyncio
async def test_get_customer_neo4j():
    """
    Tests getting a TPC-H customer from Neo4j,
    using the catalogue for routing.
    """
    async with PolyClient() as c:
        # 'customer' is mapped to 'neo4j' in schemas.json
        # We use the catalogue-defined pk 'c_custkey'
        doc = await c.get(
            "customer",
            CUSTOMER_ID,
            primary_key_column="c_custkey",
            engine="neo4j",
        )
        assert doc["c_name"] == EXPECTED_NAME


@pytest.mark.asyncio
async def test_get_customer_redis_string_by_default():
    async with PolyClient({"data_type": "string"}) as c:
        doc = await c.get(
            "Customer",
            "1",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )  # Use the logical name and simple PK
        logging.info(f"doc: {doc}")
        assert doc["c_name"] == EXPECTED_NAME


@pytest.mark.asyncio
async def test_get_customer_redis_hash():
    async with PolyClient({"data_type": "hash"}) as c:
        doc = await c.get(
            "Customer",
            "1:hash",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )
        assert doc["c_name"] == EXPECTED_NAME


@pytest.mark.asyncio
async def test_get_customer_redis_json():
    async with PolyClient({"data_type": "json"}) as c:
        doc = await c.get(
            "Customer",
            "1:json",
            primary_key_column="customerID",
            engine="redis",  # noqa: F501
        )
        assert doc["c_name"] == EXPECTED_NAME
