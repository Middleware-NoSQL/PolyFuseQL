from typing import Dict, Any

from neo4j import AsyncGraphDatabase

from polyfuseql.utils.utils import _env


class Neo4jConnector:
    def __init__(self) -> None:
        host = _env("NEO4J_HOST", "localhost")
        port = _env("NEO4J_PORT", "7687")
        user = _env("NEO4J_USER", "neo4j")
        password = _env("NEO4J_PASSWORD", "password")
        uri = f"bolt://{host}:{port}"
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def ping(self) -> bool:
        async with self._driver.session() as s:
            await s.run("RETURN 1")
            return True

    async def count(self, label: str) -> int:
        async with self._driver.session() as s:
            query = f"MATCH (n:{label.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"]

    async def get(self, label: str, pk: str) -> Dict[str, Any]:
        async with self._driver.session() as s:
            query_customers = (
                f"MATCH (n:{label.capitalize()} "
                f"{{customerId: $id}}) "
                f"RETURN properties(n) AS p"
            )
            query_productors = (
                f"MATCH (n:{label.capitalize()} "
                f"{{productId: $id}}) "
                f"RETURN properties(n) AS p"
            )
            if label == "customers":
                cypher = query_customers
            else:
                cypher = query_productors

            result = await s.run(cypher, id=pk)
            rec = await result.single()
            return rec["p"] if rec else {}
