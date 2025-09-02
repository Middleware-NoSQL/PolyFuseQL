# ruff: disable=F501
import asyncio
import decimal
import json
from pathlib import Path

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

# Define the base directory for TPC-H data files.
FIXTURE_DIR = Path(__file__).parent.parent / "docker" / "tpch-data"
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
OUTPUT_FILE = Path(__file__).parent / "ground_truth_q1.json"


def round_results(results):
    """Rounds all decimal/float values in the results for comparison."""
    for row in results:
        for key, value in row.items():
            if isinstance(value, (decimal.Decimal, float)):
                row[key] = round(value, 4)
    return results


async def load_data_into_postgres(client):
    """Helper function to load all TPC-H data into PostgreSQL."""
    print("Loading data into PostgreSQL...")
    loader_connector = client.backends["postgres"]
    for table, filepath in TABLE_FILES.items():
        if filepath.exists():
            print(f"  Loading {table}...")
            await loader_connector.bulk_insert(table, str(filepath))
        else:
            raise FileNotFoundError(f"Data file not found: {filepath}")
    print("PostgreSQL data loading complete.")


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Decimal objects."""

    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


async def main():
    """Main function to generate and save the ground truth."""
    async with PolyClient.PolyClient() as client:
        # Load data into PostgreSQL to establish the ground truth.
        await load_data_into_postgres(client)

        # Execute the query to get the definitive results.
        print("\nExecuting TPC-H Query 1 on PostgreSQL...")
        results = await client.execute(TPCH_QUERY_1, engine="postgres")
        if not results:
            print("Error: PostgreSQL did not return any results.")
            return

        # Round and sort for stable comparison.
        expected = round_results(results)
        expected.sort(key=lambda x: (x["lReturnflag"], x["lLinestatus"]))
        print("Ground truth query executed successfully.")

        # Save the results to a JSON file.
        with open(OUTPUT_FILE, "w") as f:
            json.dump(expected, f, indent=2, cls=DecimalEncoder)
        print(f"\nGround truth saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
