# tests/test_query_part.py
# This file REPLACES tests/test_query_product.py
# It tests querying the TPC-H 'part' table from PostgreSQL.
import pytest
import pytest_asyncio
from pathlib import Path
from polyfuseql.client.PolyClient import PolyClient

# We'll query for p_partkey = 2132 from the TPC-H fixtures
PART_ID = 2132
EXPECTED_NAME = "ivory rosy black steel"

# Define the path to the fixture file
FIXTURE_DIR = Path(__file__).parent / "fixtures"
PART_FIXTURE = FIXTURE_DIR / "part.tbl"

DATABASE_TYPE = "PostgreSQL"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def populate_databases(database_type: str = DATABASE_TYPE):
    """
    Module-scoped fixture to load part data into Postgres
    before tests run.
    """
    if not PART_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {PART_FIXTURE}")

    print("\n--- Populating databases for test_query_part ---")
    async with PolyClient() as client:
        if database_type == "PostgreSQL" or database_type == "ALL":
            # Load data into PostgreSQL
            pg_count = await client.bulk_load_table(
                "part", str(PART_FIXTURE), "postgres"
            )
            print(f"Loaded {pg_count} records into Postgres.")
    print("--- Database population complete ---")


@pytest.mark.asyncio
async def test_query_part_postgres():
    """
    Tests querying a TPC-H 'part' from PostgreSQL.
    This test now relies on the 'populate_databases' fixture.

    Note: This test queries the 'part' table from TPC-H,
    which is mapped to Postgres in schemas.json.
    """
    # The fixture 'product_in_db' is removed.
    # The 'populate_databases' fixture is now used automatically.
    async with PolyClient() as client:
        # Act: Execute the SELECT query
        rows = await client.execute(
            f"SELECT * FROM part WHERE p_partkey = {PART_ID}",
            engine="postgres",  # Explicitly target postgres
            use_catalogue=True,
        )

        # Assert: Verify that the correct data was returned
        assert rows, "Query should return the TPC-H part."
        assert len(rows) == 1, "Query should return exactly one part."
        assert rows[0]["pName"] == EXPECTED_NAME
