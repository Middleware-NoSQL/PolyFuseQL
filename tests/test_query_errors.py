import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_unknown_engine():
    async with PolyClient() as pc:
        with pytest.raises(ValueError):
            await pc.execute(
                "SELECT * FROM customers WHERE customerId = 'ALFKI'",
                engine="oracle",  # not supported yet
            )
