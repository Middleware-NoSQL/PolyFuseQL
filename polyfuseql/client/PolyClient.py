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
from typing import Dict, List, Tuple, Union, Sequence

__all__ = [
    "PolyClient",
]

import sqlglot
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.ConnectorFactory import ConnectorFactory
from polyfuseql.strategy.Insert import InsertStrategy
from polyfuseql.strategy.Select import SelectStrategy

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
def query_parse_ast(sql: str):
    return sqlglot.parse_one(sql, dialect="mysql")


class PolyClient:
    """Facade that exposes unified helpers plus a tiny SQL router."""

    # ---------------------------------------------------------------------
    # construction / catalogue
    # ---------------------------------------------------------------------

    def __init__(self, options: Dict = None) -> None:
        self.options = options
        self.pg = ConnectorFactory.create_connector("postgres", options)
        self.rd = ConnectorFactory.create_connector("redis", options)
        self.nj = ConnectorFactory.create_connector("neo4j", options)

        self._catalogue: Catalogue = Catalogue()

        self.backends = {
            "pg": self.pg,
            "postgres": self.pg,
            "redis": self.rd,
            "neo4j": self.nj,
        }

        self.query_strategies = {
            exp.Select: SelectStrategy(),
            exp.Insert: InsertStrategy(),
        }

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
        conn = self.backends.get(backend)
        if not conn:
            raise ValueError(f"Unknown backend '{backend}'")
        obj = await conn.get(source, pk)
        return obj

        # ---------------------------------------------------------------------
        # NEW: SQL router  (MVP)
        # ---------------------------------------------------------------------

    def query_parse_validate_grammar(self, sql: str) -> Tuple | None:
        """
        Analyzes and validates the SQL query.
        Parameters
        ----------
        sql : str
            SQL statement – only a limited subset is supported.
        """
        # ------------------------------------------------------------------
        # 1. Parse & validate grammar subset
        # ------------------------------------------------------------------
        ast = sqlglot.parse_one(sql, dialect="mysql")

        if not isinstance(ast, exp.Select):
            raise NotImplementedError("Only SELECT supported at this stage")
        if ast.expressions and not (
            len(ast.expressions) == 1 and ast.expressions[0].is_star
        ):
            msg = "Only SELECT * supported (projections TBD)"
            raise NotImplementedError(msg)

        # Table name
        tbl_expr = ast.find(exp.Table)
        if not tbl_expr:
            raise NotImplementedError("No table found in query")
        table = tbl_expr.name

        # WHERE pk = literal predicate
        where_expr = ast.args.get("where")
        if isinstance(where_expr, exp.Where):
            where_expr = where_expr.this
        if not isinstance(where_expr, exp.EQ):
            raise NotImplementedError("Require WHERE pk = literal predicate")
        col_expr, lit_expr = where_expr.left, where_expr.right
        if not isinstance(col_expr, exp.Column):
            raise NotImplementedError("Unsupported left-hand expression")
        if not isinstance(lit_expr, (exp.Literal, exp.Identifier)):
            raise NotImplementedError("Unsupported literal type")
        pk_col = col_expr.name
        pk_val = lit_expr.this  # unquoted value

        return table, pk_col, pk_val

    def set_backends(
        self,
        table: str,
        pk_col: str,
        engines: Union[str, Sequence[str], None] = None,
    ) -> list[str] | str | None:
        """
        Set the backends where the query will be executed.
        Parameters
        ----------
        table : str
            Table that will be queried.
        pk_col : str
            The primary key column of the table.
        engines : Union[str, Sequence[str], None] = None
            Expected engines to do the query
        """
        # ------------------------------------------------------------------
        # 2. Decide backends
        # ------------------------------------------------------------------
        if engines is None:
            catalogue = self._catalogue.get(table, ("postgres", pk_col))
            backend, expected_pk = catalogue
            backends = [backend]
        else:
            backends = [engines] if isinstance(engines, str) else list(engines)
            expected_pk = pk_col  # assume caller knows predicate column

        if pk_col.lower() != expected_pk.lower():
            raise NotImplementedError("Predicate column must be primary key")

        return backends

    async def query(self, sql: str, *, engine: str = None) -> List:
        """Execute *SELECT \\* FROM tbl WHERE pk = literal*
        against one or many backends.

        Parameters
        ----------
        sql : str
            SQL statement – only a limited subset is supported.
        engine : str
            *None* → use the catalogue‑owner backend (default).
            A backend name or list thereof → fan‑out query to each requested
            backend (`"postgres"|"redis"|"neo4j"`).
        """

        table, pk_col, pk_val = self.query_parse_validate_grammar(sql)
        print(table, pk_col, pk_val)
        if not engine:
            backend_tuple = self._catalogue.get(table, ("postgres", pk_col))
            backend, expected_pk = backend_tuple
            print(pk_col.lower(), expected_pk.lower())
            if pk_col.lower() != expected_pk.lower():
                raise ValueError(
                    f"Predicate column must be primary key, got '{pk_col}'"
                )
        else:
            backend = engine

        conn = self.backends.get(backend)
        if not conn:
            raise ValueError(f"Unknown backend '{backend}'")
        print(table)
        print(pk_val)
        row = await conn.get(table, pk_val)

        return [row] if row else []

    async def execute(self, sql: str, *, engine: str = None) -> List:
        ast = query_parse_ast(sql)
        strategy = self.query_strategies.get(type(ast))
        if not strategy:
            raise NotImplementedError(f"Unsupported query type: {type(ast)}")

        table = ast.find(exp.Table).name
        backend, _ = self._catalogue.get(table, (engine or "postgres", ""))
        if backend not in self.backends:
            raise ValueError(f"Unknown backend '{backend}'")

        return await strategy.execute(self, ast, backend)
