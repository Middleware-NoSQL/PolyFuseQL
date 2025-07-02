# tests/test_query_unsupported.py
import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_query_unsupported():
    async with PolyClient() as c:
        with pytest.raises(NotImplementedError):
            await c.execute(
                "ALTER name, colum FROM customers,employees", engine="neo4j"
            )
