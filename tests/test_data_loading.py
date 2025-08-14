import pytest
from pathlib import Path
from polyfuseql.client import PolyClient
from neo4j.time import Date as NeoDate

# Define the paths to the fixture files
FIXTURE_DIR = Path(__file__).parent / "fixtures"
REGION_FIXTURE = FIXTURE_DIR / "region.tbl"
LINEITEM_FIXTURE = FIXTURE_DIR / "lineitem_q1.tbl"


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_data_type", ["hash", "string", "json"])
async def test_redis_data_types(redis_data_type):
    """
    Acceptance Test for US 3.1: Verifies that the Redis loader
    correctly casts numeric types for various Redis data structures.
    """
    async with PolyClient.PolyClient() as client:
        # Arrange: Configure the Redis connector for the specific data type
        redis_conn = client.backends["redis"]
        redis_conn._options["data_type"] = redis_data_type

        # Act: Load the lineitem data using the connector's public method
        await redis_conn.bulk_insert("lineitem", str(LINEITEM_FIXTURE))

        # Act: Fetch a specific, known record using the
        # connector's public get method
        retrieved_data = await redis_conn.get(
            "lineitem", pk_col="composite_key", pk_val="1:1"
        )

        # Assert: Check the data types of numeric fields
        msg = f"Record not found in Redis for type {redis_data_type}."
        assert retrieved_data, msg

        assert isinstance(retrieved_data.get("l_quantity"), float)
        assert isinstance(retrieved_data.get("l_extendedprice"), float)
        assert retrieved_data.get("l_quantity") == 17.00
        assert retrieved_data.get("l_extendedprice") == 21168.23


@pytest.mark.asyncio
async def test_neo4j_data_types_and_parsing():
    """
    Acceptance Test for US 3.1: Verifies that the Neo4j loader
    handles malformed rows (trailing delimiters) and correctly casts
    data types (numeric and date).
    """
    async with PolyClient.PolyClient() as client:
        neo4j_conn = client.backends["neo4j"]

        # Arrange & Act (Part 1): Load region data,
        # which has trailing delimiters
        inserted_count, total_lines = await neo4j_conn.bulk_insert(
            "region", str(REGION_FIXTURE)
        )

        # Assert (Part 1): Check that no rows were skipped
        msg = "Should not skip rows with trailing delimiters."
        assert inserted_count == 5, msg
        assert total_lines == 5

        # Arrange & Act (Part 2): Load lineitem data
        await neo4j_conn.bulk_insert("lineitem", str(LINEITEM_FIXTURE))

        # Assert (Part 2): Fetch a record and check its data types
        driver = neo4j_conn._get_driver()
        query = (
            "MATCH (n:Lineitem {l_orderkey: 1, l_linenumber: 1}) "
            "RETURN n.l_quantity, n.l_extendedprice, n.l_shipdate"
        )
        async with driver.session() as session:
            result = await session.run(query)
            record = await result.single()

        assert record, "Record not found in Neo4j."
        assert isinstance(record["n.l_quantity"], float)
        assert isinstance(record["n.l_extendedprice"], float)
        assert isinstance(record["n.l_shipdate"], NeoDate)
        assert record["n.l_quantity"] == 17.00
        assert record["n.l_shipdate"] == NeoDate(1996, 3, 13)
