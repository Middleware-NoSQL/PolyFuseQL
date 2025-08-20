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
SUM(l_extendedprice)                                  AS sum_base_price, \
SUM(l_extendedprice * (1 - l_discount))               AS sum_disc_price, \
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

# Expected results based on the provided fixture data
EXPECTED_RESULT_Q1 = [
    {
        "lReturnflag": "A",
        "lLinestatus": "F",
        "sumQty": decimal.Decimal("142.00"),
        "sumBasePrice": decimal.Decimal("206668.09"),
        "sumDiscPrice": decimal.Decimal("190541.1008"),
        "sumCharge": decimal.Decimal("197576.4053"),
        "avgQty": decimal.Decimal("28.4000"),
        "avgPrice": decimal.Decimal("41333.6180"),
        "avgDisc": decimal.Decimal("0.0660"),
        "countOrder": 5,
    },
    {
        "lReturnflag": "N",
        "lLinestatus": "O",
        "sumQty": decimal.Decimal("386.00"),
        "sumBasePrice": decimal.Decimal("519377.95"),
        "sumDiscPrice": decimal.Decimal("484022.6844"),
        "sumCharge": decimal.Decimal("504750.7298"),
        "avgQty": decimal.Decimal("25.7333"),
        "avgPrice": decimal.Decimal("34625.1967"),
        "avgDisc": decimal.Decimal("0.0653"),
        "countOrder": 15,
    },
    {
        "lReturnflag": "R",
        "lLinestatus": "F",
        "sumQty": decimal.Decimal("163.00"),
        "sumBasePrice": decimal.Decimal("208243.51"),
        "sumDiscPrice": decimal.Decimal("194976.6738"),
        "sumCharge": decimal.Decimal("199678.7326"),
        "avgQty": decimal.Decimal("32.6000"),
        "avgPrice": decimal.Decimal("41648.7020"),
        "avgDisc": decimal.Decimal("0.0580"),
        "countOrder": 5,
    },
]

# Path to the small fixture file for this test
FIXTURE_DIR = Path(__file__).parent / "fixtures"
LINEITEM_FIXTURE = FIXTURE_DIR / "lineitem_q1.tbl"
ORDERS_FIXTURE = FIXTURE_DIR / "orders_q1.tbl"
CUSTOMER_FIXTURE = FIXTURE_DIR / "customer.tbl"
NATION_FIXTURE = FIXTURE_DIR / "nation.tbl"
REGION_FIXTURE = FIXTURE_DIR / "region.tbl"
PART_FIXTURE = FIXTURE_DIR / "part.tbl"
SUPPLIER_FIXTURE = FIXTURE_DIR / "supplier.tbl"
PARTSUPP_FIXTURE = FIXTURE_DIR / "partsupp.tbl"

# FIXTURE_DIR = Path(Path(__file__).parent).parent / "docker" / "tpch-data"
# LINEITEM_FIXTURE = FIXTURE_DIR / "lineitem.tbl"
# ORDERS_FIXTURE = FIXTURE_DIR / "orders.tbl"
# CUSTOMER_FIXTURE = FIXTURE_DIR / "customer.tbl"
# NATION_FIXTURE = FIXTURE_DIR / "nation.tbl"
# REGION_FIXTURE = FIXTURE_DIR / "region.tbl"
# PART_FIXTURE = FIXTURE_DIR / "part.tbl"
# SUPPLIER_FIXTURE = FIXTURE_DIR / "supplier.tbl"
# PARTSUPP_FIXTURE = FIXTURE_DIR / "partsupp.tbl"


def round_results(results):
    """Rounds all decimal/float values in the results for comparison."""
    for row in results:
        for key, value in row.items():
            if isinstance(value, (decimal.Decimal, float)):
                row[key] = round(value, 4)
    return results


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["postgres", "redis", "neo4j"])
async def test_tpch_query1(engine):
    """
    Tests TPC-H Query 1 against all supported backends.
    """
    async with PolyClient.PolyClient() as client:
        # First, ensure the fixture data is loaded into the target database
        loader_connector = client.backends[engine]

        # Redis doesn't have foreign key constraints,
        # so we can skip loading parent tables
        # if engine != "redis":
        await loader_connector.bulk_insert("region", str(REGION_FIXTURE))
        await loader_connector.bulk_insert("nation", str(NATION_FIXTURE))
        await loader_connector.bulk_insert("part", str(PART_FIXTURE))
        await loader_connector.bulk_insert("supplier", str(SUPPLIER_FIXTURE))
        await loader_connector.bulk_insert("partsupp", str(PARTSUPP_FIXTURE))
        await loader_connector.bulk_insert("customer", str(CUSTOMER_FIXTURE))
        await loader_connector.bulk_insert("orders", str(ORDERS_FIXTURE))

        await loader_connector.bulk_insert("lineitem", str(LINEITEM_FIXTURE))

        # Now, execute the query through the middleware
        results = await client.execute(TPCH_QUERY_1, engine=engine)

        # Round both actual and expected results for safe comparison
        rounded_res = round_results(results)
        rounded_expect = round_results(EXPECTED_RESULT_Q1)

        # Sort results to ensure consistent order for comparison
        rounded_res.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))
        rounded_expect.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))

        assert rounded_res == rounded_expect
