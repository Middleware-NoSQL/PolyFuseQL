import asyncio
from pathlib import Path

from polyfuseql.client import PolyClient

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


async def load_data_into_neo4j(client):
    """Helper function to load all TPC-H data into Neo4j."""
    print("Loading all TPC-H data into Redis...")
    loader_connector = client.backends["redis"]
    for table, filepath in TABLE_FILES.items():
        if filepath.exists():
            print(f"  Loading {table}...")
            await loader_connector.bulk_insert(table, str(filepath))
        else:
            raise FileNotFoundError(f"Data file not found: {filepath}")
    print("Redis data loading complete.")


async def main():
    """Main function to run the Neo4j population script."""
    async with PolyClient.PolyClient() as client:
        await load_data_into_neo4j(client)


if __name__ == "__main__":
    asyncio.run(main())
