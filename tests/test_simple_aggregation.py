import logging

import pytest
from pathlib import Path
from polyfuseql.client import PolyClient

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SALES_FIXTURE = FIXTURE_DIR / "sales.tbl"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["redis", "neo4j"])
async def test_simple_aggregations(engine):
    """
    Tests basic SUM, AVG, and COUNT aggregations on a simple dataset.
    """
    async with PolyClient.PolyClient() as client:
        connector = await client.get_connector(engine)
        await connector.bulk_insert("sales", str(SALES_FIXTURE))

        # Test SUM
        sql_sum = "SELECT SUM(amount) AS total_sales FROM Sales"
        result_sum = await client.execute(sql_sum, engine=engine)
        logging.info(f"Result: {result_sum}")
        assert result_sum[0]["totalSales"] == 600.0

        # Test AVG
        sql_avg = "SELECT AVG(amount) AS avg_sale FROM Sales"
        result_avg = await client.execute(sql_avg, engine=engine)
        logging.info(f"result_avg: {result_avg}")
        assert result_avg[0]["avgSale"] == 150.0

        # Test COUNT
        sql_count = "SELECT COUNT(*) AS num_sales FROM Sales"
        result_count = await client.execute(sql_count, engine=engine)
        logging.info(f"result_count: {result_count}")
        assert result_count[0]["numSales"] == 4
