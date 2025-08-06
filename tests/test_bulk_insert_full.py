# tests/test_bulk_insert_full.py
import pytest
from pathlib import Path
from polyfuseql.client import PolyClient
from polyfuseql.utils.tpch_schema import TPCH_TABLE_ORDER

DATA_DIR = Path(__file__).parent.parent / "docker" / "tpch-data"


@pytest.mark.asyncio
async def test_bulk_insert_full_postgres():
    """
    Tests bulk insertion of the full TPC-H dataset into PostgreSQL.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in TPCH_TABLE_ORDER:
            file_path = DATA_DIR / f"{table_name}.tbl"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "postgres"
            )
            assert inserted_count > 0


@pytest.mark.asyncio
async def test_bulk_insert_full_redis():
    """
    Tests bulk insertion of the full TPC-H dataset into Redis.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in TPCH_TABLE_ORDER:
            file_path = DATA_DIR / f"{table_name}.tbl"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "redis"
            )
            assert inserted_count > 0


@pytest.mark.asyncio
async def test_bulk_insert_full_neo4j():
    """
    Tests bulk insertion of the full TPC-H dataset into Neo4j.
    """
    async with PolyClient.PolyClient() as client:
        for table_name in TPCH_TABLE_ORDER:
            file_path = DATA_DIR / f"{table_name}.tbl"
            inserted_count = await client.bulk_load_table(
                table_name, str(file_path), "neo4j"
            )
            assert inserted_count > 0
