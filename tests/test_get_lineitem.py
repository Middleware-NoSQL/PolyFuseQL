# tests/test_get_lineitem.py
# It tests fetching 'lineitem' from Redis, as defined in schemas.json.
import pytest
import pytest_asyncio
from pathlib import Path
from polyfuseql.client.PolyClient import PolyClient

# We will query for l_orderkey = 1, l_linenumber = 1
# This corresponds to the TPC-H fixture data.
# The composite PK will be "1:1"
LINEITEM_PK = "1:1"

# Define the path to the fixture file
FIXTURE_DIR = Path(__file__).parent / "fixtures"
LINEITEM_FIXTURE = FIXTURE_DIR / "lineitem.tbl"

# Set to "Redis_All" to populate all Redis types
DATABASE_TYPE = "Redis_All"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def populate_databases(database_type: str = DATABASE_TYPE):
    """
    Module-scoped fixture to load lineitem data into Redis
    before tests run.
    """
    if not LINEITEM_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {LINEITEM_FIXTURE}")

    print("\n--- Populating databases for test_get_lineitem ---")
    async with PolyClient() as client:
        # Default string type
        if database_type == "Redis" or database_type == "Redis_All":
            client.options = {
                "data_type": "string",
                "include_data_type_in_pk": True,
            }
            rd_count = await client.bulk_load_table(
                "lineitem", str(LINEITEM_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis (String).")

        if database_type == "Redis_Hash" or database_type == "Redis_All":
            # Load data into Redis Hash
            client.options = {
                "data_type": "hash",
                "include_data_type_in_pk": True,
            }  # noqa:E501
            rd_count = await client.bulk_load_table(
                "lineitem", str(LINEITEM_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis (Hash).")
        if database_type == "Redis_Json" or database_type == "Redis_All":
            # Load data into Redis Json
            client.options = {
                "data_type": "json",
                "include_data_type_in_pk": True,
            }  # noqa:E501
            rd_count = await client.bulk_load_table(
                "lineitem", str(LINEITEM_FIXTURE), "redis"
            )
            print(f"Loaded {rd_count} records into Redis (JSON).")
    print("--- Database population complete ---")


@pytest.mark.asyncio
async def test_get_lineitem_redis_string():
    options = {"data_type": "string", "include_data_type_in_pk": True}
    async with PolyClient(options=options) as c:
        # The catalogue maps 'lineitem' to Redis and its composite PK
        doc = await c.get(
            "lineitem",
            f"{LINEITEM_PK}:string",
            primary_key_column="l_orderkey:l_linenumber",
            engine="redis",
        )
        assert doc
        assert doc["l_quantity"] == 17.0
        assert doc["l_extendedprice"] == 21168.23


@pytest.mark.asyncio
async def test_get_lineitem_redis_hash():
    options = {"data_type": "hash", "include_data_type_in_pk": True}
    async with PolyClient(options=options) as c:
        doc = await c.get(
            "lineitem",
            f"{LINEITEM_PK}:hash",
            primary_key_column="l_orderkey:l_linenumber",
            engine="redis",
        )
        assert doc
        assert doc["l_quantity"] == 17.0
        assert doc["l_extendedprice"] == 21168.23


@pytest.mark.asyncio
async def test_get_lineitem_redis_json():
    options = {"data_type": "json", "include_data_type_in_pk": True}
    async with PolyClient(options=options) as c:
        doc = await c.get(
            "lineitem",
            f"{LINEITEM_PK}:json",
            primary_key_column="l_orderkey:l_linenumber",
            engine="redis",
        )
        assert doc
        assert doc["l_quantity"] == 17.0
        assert doc["l_extendedprice"] == 21168.23
