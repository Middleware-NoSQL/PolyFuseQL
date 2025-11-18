# tests/test_query_customer_neo4j.py
import logging

import pytest
import pytest_asyncio
from pathlib import Path
from polyfuseql.client.PolyClient import PolyClient

# Define the path to the fixture file
FIXTURE_DIR = Path(__file__).parent / "fixtures"
CUSTOMER_FIXTURE = FIXTURE_DIR / "customer.tbl"

DATABASE_TYPE = "Neo4j"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def populate_databases(database_type: str = DATABASE_TYPE):
    """
    Module-scoped fixture to load customer data into Neo4j
    before tests run.
    """
    if not CUSTOMER_FIXTURE.exists():
        pytest.fail(f"Fixture file not found: {CUSTOMER_FIXTURE}")

    print("\n--- Populating databases for test_query_customer_neo4j ---")
    async with PolyClient() as client:
        if database_type == "Neo4j" or database_type == "ALL":
            # Load data into Neo4j
            nj_count = await client.bulk_load_table(
                "customer", str(CUSTOMER_FIXTURE), "neo4j"
            )
            print(f"Loaded {nj_count} records into Neo4j.")
    print("--- Database population complete ---")


@pytest.mark.asyncio
async def test_query_customer_neo4j():
    """
    Tests querying the TPC-H 'customer' table from Neo4j.
    Uses 'c_custkey' as per schemas.json.
    """
    async with PolyClient() as c:
        # The catalogue maps 'customer' to 'neo4j'
        rows = await c.execute(
            "SELECT * FROM customer WHERE c_custkey = 1",
            engine="neo4j",
            use_catalogue=True,
        )
        # Neo4j connector returns snake_case properties
        logging.info(f"rows: {rows}")
        assert rows and rows[0]["cName"] == "Customer#000000001"
