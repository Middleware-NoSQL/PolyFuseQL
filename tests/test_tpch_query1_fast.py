# ruff: disable=F501
import decimal
import json
from pathlib import Path

import pytest
import pytest_asyncio
from polyfuseql.client import PolyClient

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
               """

GROUND_TRUTH_FILE = Path(__file__).parent / "ground_truth_q1.json"


def round_results(results):
    """Rounds all decimal/float values in the results for comparison."""
    for row in results:
        for key, value in row.items():
            if isinstance(value, (decimal.Decimal, float)):
                # Round to 4 decimal places for consistent comparison.
                row[key] = round(float(value), 4)
    return results


@pytest.fixture(scope="session")
def ground_truth_from_file():
    """
    Loads the pre-computed ground truth results from the JSON file.
    This fixture is session-scoped, so the file is only read once.
    """
    if not GROUND_TRUTH_FILE.exists():
        pytest.fail(
            f"Ground truth file not found: {GROUND_TRUTH_FILE}\n"
            "Please run generate_ground_truth.py first.",
            pytrace=False,
        )
    with open(GROUND_TRUTH_FILE, "r") as f:
        return json.load(f)


@pytest_asyncio.fixture(scope="function")
async def poly_client():
    """Creates a new client for each test function."""
    async with PolyClient.PolyClient() as client:
        yield client


@pytest.mark.asyncio
async def test_tpch_query1_neo4j_fast(poly_client, ground_truth_from_file):
    """
    Tests TPC-H Query 1 against Neo4j by comparing its result to the
    pre-computed ground truth from a file.
    """
    # Step 1: Execute the query on Neo4j (assumes data is already loaded).
    print("\nExecuting query on Neo4j...")
    results = await poly_client.execute(TPCH_QUERY_1, engine="neo4j")
    print("Query executed on Neo4j.")

    # Step 2: Round and sort the actual results from Neo4j.
    rounded_res = round_results(results)
    rounded_res.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))

    # Step 3: Compare the Neo4j result with the loaded ground truth.
    assert (
        rounded_res == ground_truth_from_file
    ), "Results for Neo4j do not match the pre-computed ground truth."
    print("Assertion successful: Neo4j results match ground truth.")
