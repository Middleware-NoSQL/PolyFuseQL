# ruff: noqa: E501
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
      SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, \
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
"""  # noqa:F501

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


@pytest.mark.asyncio
async def test_tpch_query1_dynamically():
    """
    Tests TPC-H Query 1 against all supported backends using PostgreSQL as the
    source of truth for the expected results.
    """
    async with PolyClient.PolyClient() as client:
        # Step 1: Load the same generated data into all database engines.
        all_engines = ["postgres", "redis", "neo4j"]
        for engine in all_engines:
            await load_data_into_engine(client, engine)

        # Step 2: Execute the query on PostgreSQL to get the ground truth.
        ground_truth_results = await client.execute(
            TPCH_QUERY_1, engine="postgres"
        )  # noqa:F501

        # The ground truth must not be empty.
        assert ground_truth_results, "PostgreSQL did not return any results."

        # Round and sort the ground truth results for stable comparison.
        expected_results = round_results(ground_truth_results)
        expected_results.sort(
            key=lambda x: (x["lReturnflag"], x["lLinestatus"])
        )  # noqa:F501

        # Step 3: Test the other engines (Redis, Neo4j)
        # against the ground truth.
        for engine in ["redis", "neo4j"]:
            # Execute the query on the current engine.
            results = await client.execute(TPCH_QUERY_1, engine=engine)

            # Round and sort the actual results.
            rounded_res = round_results(results)
            rounded_res.sort(
                key=lambda x: (x["lReturnflag"], x["lLinestatus"])
            )  # noqa:F501

            # Compare the engine's result with the ground truth
            # from PostgreSQL.
            assert (
                rounded_res == expected_results
            ), f"Results for {engine} do not match PostgreSQL."
