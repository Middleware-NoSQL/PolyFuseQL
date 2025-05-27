from typing import Dict, Any

from polyfuseql.connector.Connector import Connector
from neo4j import AsyncGraphDatabase

from polyfuseql.utils.utils import env


class Neo4jConnector(Connector):
    def __init__(self, options: Dict = None) -> None:
        super().__init__(options)
        host = env("NEO4J_HOST", "localhost")
        port = env("NEO4J_PORT", "7687")
        user = env("NEO4J_USER", "neo4j")
        password = env("NEO4J_PASSWORD", "password")
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
        """Fetch one node by its *possible* primary‑key property.

        The seed dataset is inconsistent (`customerId` vs `CustomerID` vs
        `entityId`).  Try a list of candidate property names until a match
        is found.  Returns an empty dict if nothing matches.
        """
        prop_candidates = [
            f"{label}Id",  # customerId / productId
            f"{label}ID",  # customerID / productID
            "CustomerID",
            "ProductID",  # specific Northwind convention
            "entityId",
            "id",
        ]

        async with self._driver.session() as s:
            for prop in prop_candidates:
                cypher = (
                    f"MATCH (n:{label.capitalize()}) "
                    f"WHERE n.{prop} = $id RETURN properties(n) AS p LIMIT 1"
                )
                rec = await (await s.run(cypher, id=pk)).single()
                if rec and rec["p"]:
                    return rec["p"]
        return {}
