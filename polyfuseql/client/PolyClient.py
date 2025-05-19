"""polyfuseql.client.PolyClient
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified façade that hides individual datastore connectors.
This update adds a minimal *read‑only* SQL router using **sqlglot**.
Supported grammar (MVP):
    SELECT * FROM <table> WHERE <pkCol> = <literal>

If the table is not found in the in‑memory catalogue the query falls
back to Postgres.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

__all__ = [
    "PolyClient",
]

import sqlglot
from sqlglot import exp

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


# ---------------------------------------------------------------------------
# PolyClient
# ---------------------------------------------------------------------------
class PolyClient:
    """Facade that exposes unified helpers plus a tiny SQL router."""

    # ---------------------------------------------------------------------
    # construction / catalogue
    # ---------------------------------------------------------------------

    def __init__(self, mapping_path: str | Path | None = None) -> None:
        self.pg = PostgresConnector()
        self.rd = RedisConnector()
        self.nj = Neo4jConnector()

        self._catalogue: Dict[str, Tuple[str, str]] = {}
        self._load_mapping(mapping_path)

    # .................................................................
    # internal: mapping loader
    # .................................................................

    def _load_mapping(self, mapping_path: str | Path | None) -> None:
        """Populate ``self._catalogue`` with table → (backend, pkColumn).

        Order of precedence:
        1. *mapping_path* arg if provided.
        2. ``$POLYFUSEQL_MAPPING`` env‑var.
        3. Built‑in defaults.
        """
        path: Path | None = None
        if mapping_path:
            path = Path(mapping_path)
        elif os.getenv("POLYFUSEQL_MAPPING"):
            path = Path(os.environ["POLYFUSEQL_MAPPING"])

        if path and path.exists():
            data = json.loads(path.read_text())
            for tbl, spec in data.items():
                self._catalogue[tbl.lower()] = (spec["backend"], spec["pk"])
        else:
            # built‑in minimal mapping
            self._catalogue.update(
                {
                    "customers": ("redis", "customerId"),
                    "products": ("pg", "productId"),
                    "customer": ("neo4j", "customerId"),  # node label
                    "product": ("neo4j", "productId"),
                }
            )

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

        # ---------------------------------------------------------------------
        # NEW: SQL router  (MVP)
        # ---------------------------------------------------------------------

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        """Parse *SELECT \\* FROM tbl WHERE pk = literal* and delegate.

        Returns a list of dict rows (empty if no match).
        Raises *NotImplementedError* when query is outside the MVP subset.
        """
        ast = sqlglot.parse_one(sql, dialect="mysql")
        print("ast args", ast.args)
        # 1. accept *only* SELECT *
        if not isinstance(ast, exp.Select):
            raise NotImplementedError("Only SELECT supported at this stage")
        if ast.expressions and not (
            len(ast.expressions) == 1 and ast.expressions[0].is_star
        ):
            msg = "Only SELECT * supported (projections TBD)"
            raise NotImplementedError(msg)

        # 2. extract table
        table_expr = ast.find(exp.Table)
        if not table_expr:
            raise NotImplementedError("No table found in query")
        table = table_expr.name.lower()

        # 3. extract simple equality predicate
        where_expr = ast.args.get("where")

        #  sqlglot parses `WHERE …` as       Where(this=<expression>)
        #  we want the <expression> itself.
        if isinstance(where_expr, exp.Where):
            where_expr = where_expr.this
        if not isinstance(where_expr, exp.EQ):
            raise NotImplementedError("Need WHERE pk = literal predicate")
        col_expr = where_expr.left  # Column(...)
        lit_expr = where_expr.right  # Literal or Identifier
        if not isinstance(col_expr, exp.Column) or not isinstance(
            lit_expr, (exp.Literal, exp.Identifier)
        ):
            raise NotImplementedError("Unsupported predicate components")
        pk_col = col_expr.name
        pk_val = lit_expr.this  # unquoted literal from sqlglot

        # 4. catalogue lookup or fallback
        backend, expected_pk = self._catalogue.get(table, ("pg", pk_col))
        if pk_col.lower() != expected_pk.lower():
            raise NotImplementedError("Predicate column must be primary key")

        # 5. delegate to connectors
        if backend == "redis":
            row = await self.rd.get(table.rstrip("s"), pk_val)
        elif backend == "neo4j":
            row = await self.nj.get(table.rstrip("s"), pk_val)
        else:  # postgres default
            row = await self.pg.get(table, pk_val)

        return [row] if row else []
