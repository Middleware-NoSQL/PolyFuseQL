"""polyfuseql core – thin async connectors and PolyClient façade.

Public surface:
    class PolyClient  –  async context‑manager holding three lightweight
                        connectors (Postgres, Redis, Neo4j).

Each connector exposes the minimal trio needed for the first TDD cycle:
    • ping()   – sanity check the wire/credentials.
    • count()  – number of entities of a logical type.
    • get()    – fetch one entity by primary key, returning a Python dict.

Assumes docker‑compose defaults:
    postgres → host "postgres", db/user/pass "northwind" (port 5432)
    redis    → host "redis", port 6379
    neo4j    → bolt://neo4j:7687  user neo4j / password password

The mapping from logical collection name to physical store is currently
hard‑coded in _ROUTER; it will later be driven by SQLGlot parsing.
"""

from typing import Dict, Tuple

__all__ = [
    "PostgresConnector",
    "RedisConnector",
    "Neo4jConnector",
    "PolyClient",
]

from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.Redis import RedisConnector

# ────────────────────────────────  Router  ────────────────────────────── #
# logical_name → (engine_attr_on_client, concrete_name_in_store)
_ROUTER: Dict[str, Tuple[str, str]] = {
    "customers": ("pg", "customers"),
    "products": ("pg", "products"),
}

_MAPPING: Dict[str, Tuple[str, str]] = {
    "customers": ("pg", "customers"),
    "products": ("pg", "products"),
}


# ─────────────────────────────  Facade client  ─────────────────────────── #
class PolyClient:
    """Route logical entities to physical back‑ends.
    "">>> c = PolyClient()
    "">>> await c.count("customers")
    91
    """

    def __init__(self) -> None:
        self.pg = PostgresConnector()
        self.rd = RedisConnector()
        self.nj = Neo4jConnector()

    async def count(self, logical: str, backend: str = "") -> int:
        if not backend:
            backend, source = _MAPPING[logical]
        source = logical
        print(backend, source)
        match backend:
            case "pg":
                return await self.pg.count(source)
            case "redis":
                return await self.rd.count(source)
            case "neo4j":
                return await self.nj.count(source)
            case _:
                raise ValueError(f"Unknown backend: {backend}")

    async def get(self, logical: str, pk: str, backend: str = "") -> Dict:
        if not backend:
            backend, source = _MAPPING[logical]
        source = logical
        print(backend, source)
        match backend:
            case "pg":
                obj = await self.pg.get(source, pk)
            case "redis":
                obj = await self.rd.get(source, pk)
            case "neo4j":
                obj = await self.nj.get(source, pk)
            case _:
                raise ValueError("Unknown backend")
        return obj
