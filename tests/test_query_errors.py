import pytest
from polyfuseql.client.PolyClient import PolyClient


@pytest.mark.asyncio
async def test_unknown_engine():
    pc = PolyClient()
    with pytest.raises(ValueError):
        await pc.query(
            "SELECT * FROM customers WHERE customerId = 'ALFKI'",
            engine="oracle",  # not supported yet
        )
