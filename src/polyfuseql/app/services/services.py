# src/polyfuseql/app/services/services.py
"""
Service layer to abstract business logic from API endpoints.
"""
from polyfuseql.client.PolyClient import PolyClient
from typing import Any, List


async def execute_query(engine: str, sql: str) -> List[Any]:
    """
    Executes a query on the specified database engine.

    Args:
        engine: The name of the database engine (e.g., 'postgres').
        sql: The SQL query to execute.

    Returns:
        The result of the query.
    """
    async with PolyClient() as client:
        # The `use_catalogue=False` flag is important here because we are
        # explicitly telling the client which
        # engine to use based on the endpoint.
        result = await client.execute(sql, engine=engine, use_catalogue=False)
        return result
