# ruff: disable=F501
import pytest
from pathlib import Path
from polyfuseql.client import PolyClient
import decimal

# TPC-H Query 1 - Pricing Summary Report
TPCH_QUERY_1 = """
SELECT l_returnflag, \
      l_linestatus, \
      SUM(l_quantity)                                       AS sum_qty, \
      SUM(l_extendedprice)                                  AS sum_base_price,\
      SUM(l_extendedprice * (1 - l_discount))               AS sum_disc_price,\
      SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,\
      AVG(l_quantity)                                       AS avg_qty, \
      AVG(l_extendedprice)                                  AS avg_price, \
      AVG(l_discount)                                       AS avg_disc, \
      COUNT(*)                                              AS count_order
FROM lineitem
WHERE l_shipdate <= date '1998-09-02'
GROUP BY l_returnflag, \
        l_linestatus
ORDER BY l_returnflag, \
        l_linestatus; \
               """

# Define the base directory for TPC-H data files.
FIXTURE_DIR = Path(Path(__file__).parent).parent / "docker" / "tpch-data"
TABLE_FILES = {
    "region": FIXTURE_DIR / "region.tbl",
    "nation": FIXTURE_DIR / "nation.tbl",
    "part": FIXTURE_DIR / "part.tbl",
    "supplier": FIXTURE_DIR / "supplier.tbl",
    "partsupp": FIXTURE_DIR / "partsupp.tbl",
    "customer": FIXTURE_DIR / "customer.tbl",
    "orders": FIXTURE_DIR / "orders.tbl",
    "lineitem": FIXTURE_DIR / "lineitem.tbl",
}


def round_results(results):
    """Rounds all decimal/float values in the results for comparison."""
    for row in results:
        for key, value in row.items():
            if isinstance(value, (decimal.Decimal, float)):
                # Round to 4 decimal places for consistent comparison.
                row[key] = round(value, 4)
    return results


async def load_data_into_engine(client, engine):
    """Helper function to load all TPC-H data into a specific engine."""
    loader_connector = client.backends[engine]
    for table, filepath in TABLE_FILES.items():
        # Ensure the data file exists before trying to load it.
        if filepath.exists():
            await loader_connector.bulk_insert(table, str(filepath))
        else:
            # Fail the test if data is missing, as results would be invalid.
            pytest.fail(f"Data file not found: {filepath}", pytrace=False)


@pytest.fixture(scope="session")
async def ground_truth_from_postgres():
    """
    Pytest fixture to establish a ground truth by executing the TPC-H query
    against PostgreSQL. This fixture is session-scoped, so it only runs once,
    and the result is cached for all tests in the session.
    """
    async with PolyClient.PolyClient() as client:
        # Load data into PostgreSQL to establish the ground truth.
        print("\nSetting up ground truth from PostgreSQL...")
        await load_data_into_engine(client, "postgres")

        # Execute the query to get the definitive results for this dataset.
        results = await client.execute(TPCH_QUERY_1, engine="postgres")
        msg = "PostgreSQL did not return any results for ground truth."
        assert results, msg  # noqa:F501

        # Round and sort for stable comparison.
        expected = round_results(results)
        expected.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))
        print("Ground truth established.")
        return expected


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["redis", "neo4j"])
async def test_tpch_query1_against_ground_truth(
    engine, ground_truth_from_postgres
):  # noqa:F501
    """
    Tests TPC-H Query 1 against specified backends (Redis, Neo4j) by
    comparing their results to the PostgreSQL ground truth.
    Use `pytest -k <engine_name>` to run for a specific engine.
    """
    async with PolyClient.PolyClient() as client:
        # Step 1: Load data into the target engine for the current test run.
        await load_data_into_engine(client, engine)

        # Step 2: Execute the query on the current engine.
        results = await client.execute(TPCH_QUERY_1, engine=engine)

        # Step 3: Round and sort the actual results from the target engine.
        rounded_res = round_results(results)
        rounded_res.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))

        # Step 4: Compare the engine's result with the cached ground truth.
        assert (
            rounded_res == ground_truth_from_postgres
        ), f"Results for {engine} do not match PostgreSQL ground truth."
