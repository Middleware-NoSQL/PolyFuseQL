# tests/test_bulk_insert_full.py
import pytest
from pathlib import Path
from polyfuseql.client import PolyClient

DATA_DIR = Path(__file__).parent.parent / "docker" / "tpch-data"


@pytest.fixture(scope="module")
def table_order(tmp_path_factory):
    # This fixture can be expanded to create temporary schema files if needed
    # For now, it just returns the table loading order.
    return [
        "region",
        "nation",
        "supplier",
        "customer",
        "part",
        "partsupp",
        "orders",
        "lineitem",
    ]


@pytest.mark.asyncio
async def test_bulk_insert_full_postgres(table_order):
    """
    Tests bulk insertion of the full TPC-H dataset into PostgreSQL.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in table_order:
            file_path = DATA_DIR / f"{table_name}.tbl"
            assert file_path.exists(), f"Data file not found: {file_path}"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "postgres"
            )
            assert inserted_count > 0


@pytest.mark.asyncio
async def test_bulk_insert_full_redis(table_order):
    """
    Tests bulk insertion of the full TPC-H dataset into Redis.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in table_order:
            file_path = DATA_DIR / f"{table_name}.tbl"
            assert file_path.exists(), f"Data file not found: {file_path}"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "redis"
            )
            assert inserted_count > 0


@pytest.mark.asyncio
async def test_bulk_insert_full_neo4j(table_order):
    """
    Tests bulk insertion of the full TPC-H dataset into Neo4j.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in table_order:
            file_path = DATA_DIR / f"{table_name}.tbl"
            assert file_path.exists(), f"Data file not found: {file_path}"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "neo4j"
            )
            print(f"\nNeo4j: Inserted {inserted_count} rows into {table_name}")
            assert inserted_count > 0
