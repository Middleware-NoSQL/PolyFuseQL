# tests/test_bulk_insert.py (New File)
import pytest
from pathlib import Path
from polyfuseql.client import PolyClient

# Define expected row counts for our small fixture files
EXPECTED_COUNTS = {
    "region": 5,
    "nation": 25,
}

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name, expected_count", EXPECTED_COUNTS.items())
async def test_bulk_insert_postgres(table_name, expected_count):
    """
    Tests bulk insertion into PostgreSQL
    using the COPY command via the connector.
    """
    file_path = FIXTURE_DIR / f"{table_name}.tbl"
    assert file_path.exists(), f"Fixture file not found: {file_path}"

    async with PolyClient.PolyClient() as client:
        # Load the data
        inserted_count = await client.bulk_load_table(
            table_name, str(file_path), "postgres"
        )
        assert inserted_count == expected_count

        # Verify by counting rows in the table
        count_after_load = await client.pg.count(table_name)
        assert count_after_load == expected_count


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name, expected_count", EXPECTED_COUNTS.items())
async def test_bulk_insert_redis(table_name, expected_count):
    """
    Tests pipelined bulk insertion into Redis.
    """
    file_path = FIXTURE_DIR / f"{table_name}.tbl"
    assert file_path.exists()

    async with PolyClient.PolyClient(
        options={"include_data_type_in_pk": True}
    ) as client:
        # Load the data
        inserted_count = await client.bulk_load_table(
            table_name, str(file_path), "redis"
        )
        assert inserted_count == expected_count

        # Verify by counting keys in the namespace
        count_after_load = await client.rd.count(table_name.capitalize())
        assert count_after_load >= expected_count


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name, expected_count", EXPECTED_COUNTS.items())
async def test_bulk_insert_neo4j(table_name, expected_count):
    """
    Tests bulk insertion into Neo4j using the LOAD CSV command.
    """
    file_path = FIXTURE_DIR / f"{table_name}.tbl"
    assert file_path.exists()

    async with PolyClient.PolyClient() as client:
        # Load the data
        inserted_count = await client.bulk_load_table(
            table_name, str(file_path), "neo4j"
        )
        assert inserted_count == expected_count

        # Verify by counting nodes with the label
        count_after_load = await client.nj.count(table_name)
        assert count_after_load >= expected_count
