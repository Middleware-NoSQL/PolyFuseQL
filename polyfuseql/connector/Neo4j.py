# ruff: noqa: F401
import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from neo4j import AsyncGraphDatabase as AGD, AsyncDriver
from polyfuseql.utils.utils import env


class Neo4jConnector(Connector):
    """Connector for Neo4j with persistent connection handling."""

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        host = env("NEO4J_HOST", "localhost")
        port = env("NEO4J_PORT", "7687")
        user = env("NEO4J_USER", "neo4j")
        password = env("NEO4J_PASSWORD", "password")
        self._uri = f"bolt://{host}:{port}"
        self._auth = (user, password)
        self._driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        if not self._driver:
            self._driver = AGD.driver(self._uri, auth=self._auth)
            logging.info("Neo4j driver initialized.")
            await self.ping()

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logging.info("Neo4j driver closed.")

    def _get_driver(self) -> AsyncDriver:
        if not self._driver:
            raise ConnectionError(
                "Neo4jConnector is not connected. Call connect() first."
            )
        return self._driver

    async def ping(self) -> bool:
        driver = self._get_driver()
        async with driver.session() as s:
            await s.run("RETURN 1")
        return True

    async def count(self, label: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{label.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    async def get(
        self, label: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        driver = self._get_driver()
        async with driver.session() as s:
            cypher_match = f"MATCH (n:{label.capitalize()}) "
            cypher_where = f"WHERE n.`{pk_col}` "  # noqa: F501
            cypher = (
                cypher_match
                + cypher_where
                + "= $pk_val RETURN properties(n) AS p LIMIT 1"
            )
            print("Neo4j-con-get-cypher", cypher)
            print("Neo4j-con-get-pk_val", pk_val)
            print("Neo4j-con-get-pk_val-type", type(pk_val))
            result = await s.run(cypher, pk_val=pk_val)
            rec = await result.single()
            return rec["p"] if rec and rec["p"] else {}

    async def insert(self, label: str, payload: Dict[str, Any]) -> Any:
        driver = self._get_driver()
        props = ", ".join(f"`{k}`: ${k}" for k in payload.keys())

        cypher = f"CREATE (n:{label.capitalize()} {{ {props} }}) "
        cypher += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher, **payload)
            rec = await result.single()
            return rec["p"] if rec else {}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    async def delete(self, label: str, pk_col: str, pk_val: Any) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = (
                f"MATCH (n:{label.capitalize()} {{{pk_col}: $pk_val}}) "
                "DETACH DELETE n"
            )
            summary = await s.run(cypher, pk_val=pk_val)
            return 1 if summary else 0

    async def update(
        self, label: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            # The "+=" operator efficiently merges properties
            # from the payload map
            cypher = f"MATCH (n:{label} {{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            summary = await s.run(cypher, pk_val=pk_val, payload=payload)
            return 1 if summary else 0
