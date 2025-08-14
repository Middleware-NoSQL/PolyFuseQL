import pytest
from polyfuseql.client import PolyClient

# A simple table of products
SIMPLE_PRODUCTS_DATA = """
1|Electronics|Laptop|1200.00
2|Electronics|Mouse|25.00
3|Books|Sci-Fi Novel|15.00
4.1|Books|History Text|150.00
5|Electronics|Keyboard|75.00
"""

SIMPLE_QUERY = """
SELECT
    category,
    SUM(price) AS total_price
FROM
    products
GROUP BY
    category
ORDER BY
    category;
"""

EXPECTED_SIMPLE_RESULTS = [
    {
        "category": "Books",
        "totalPrice": 165.00,
    },
    {
        "category": "Electronics",
        "totalPrice": 1300.00,
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["redis", "neo4j"])
async def test_simple_aggregation(engine, tmp_path):
    """
    Tests a simple GROUP BY aggregation query.
    """
    # Create a temporary fixture file
    fixture_file = tmp_path / "products.tbl"
    fixture_file.write_text(SIMPLE_PRODUCTS_DATA)

    async with PolyClient.PolyClient() as client:
        loader_connector = client.backends[engine]

        # Define a simple schema for the temp table
        # This is a workaround for not having a central schema
        # registry for temp tables
        if engine == "neo4j":
            loader_connector.TPCH_SCHEMA = {
                "products": {
                    "columns": ["id", "category", "name", "price"],
                    "pk": "id",
                }
            }
        elif engine == "redis":
            loader_connector.TPCH_SCHEMA = {
                "products": {
                    "columns": ["id", "category", "name", "price"],
                    "pk": "id",
                }
            }

        # Load the fixture data
        await loader_connector.bulk_insert("products", str(fixture_file))

        # Verify data loading
        count = await loader_connector.count("products")
        assert count > 0

        # Execute the query
        results = await client.execute(SIMPLE_QUERY, engine=engine)

        assert results == EXPECTED_SIMPLE_RESULTS
