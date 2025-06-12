"""polyfuseql.client.PolyClient
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified façade that hides individual datastore connectors.
This update adds a minimal *read‑only* SQL router using **sqlglot**.
Supported grammar (MVP):
    SELECT * FROM <table> WHERE <pkCol> = <literal>

If the table is not found in the in‑memory catalogue the query falls
back to Postgres.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple, Union, Sequence, Any

__all__ = [
    "PolyClient",
]

import sqlglot
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.ConnectorFactory import ConnectorFactory
from polyfuseql.strategy.Delete import DeleteStrategy
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
        self.options = options or {}
        self.pg = ConnectorFactory.create_connector("postgres", self.options)
        self.rd = ConnectorFactory.create_connector("redis", self.options)
        self.nj = ConnectorFactory.create_connector("neo4j", self.options)
        self._catalogue = Catalogue()
        self.backends = {
            "postgres": self.pg,
            "pg": self.pg,
            "redis": self.rd,
            "neo4j": self.nj,
        }
        self.query_strategies = {
            exp.Select: SelectStrategy(),
            exp.Insert: InsertStrategy(),
            exp.Delete: DeleteStrategy(),
        }

    # .................................................................
    # internal: mapping loader
    # .................................................................

    async def __aenter__(self):
        """Establishes connections when entering an `async with` block."""
        await asyncio.gather(
            self.pg.connect(), self.rd.connect(), self.nj.connect()
        )  # noqa: F501
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes connections when exiting an `async with` block."""
        await asyncio.gather(
            self.pg.disconnect(), self.rd.disconnect(), self.nj.disconnect()
        )

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
            self._catalogue.update({})

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

    async def get(
        self, logical_table: str, pk_val: Any, engine: str = None
    ) -> Dict:  # npqa: F501
        """
        Fetches a single record by its logical table name and
        primary key value.
        It uses the Catalogue to determine the backend and primary key column.

        Args:
            logical_table: The logical name of the table
            (e.g., 'customers').
            pk_val: The value of the primary key to look up.
            engine: (Optional) A specific backend to target,
            bypassing the catalogue.

        Returns:
            A dictionary representing the record, or an empty dict if not found
        """

        if engine:
            backend = engine

            if logical_table not in self._catalogue:
                logging.warning(
                    f"Table '{logical_table}' not in catalogue; "
                    f"cannot determine PK column for specified engine. "
                    f"Using {logical_table} instead."
                )
                pk_col = logical_table
            else:
                _, pk_col = self._catalogue[logical_table]
        else:
            # Look up backend and pk_col from the catalogue
            catalogue_entry = self._catalogue.get(logical_table)
            if not catalogue_entry:
                msg = f"Table '{logical_table}' not found in catalogue."
                raise ValueError(msg)
            backend, pk_col = catalogue_entry

        conn = self.backends.get(backend)
        if not conn:
            raise ValueError(f"Unknown backend '{backend}'")

        # Use the physical table name (which might be different) if available,
        # otherwise default to the logical name.
        physical_table = _ROUTER.get(logical_table, (None, logical_table))[1]
        print("polyclient-get-physical_table", physical_table)
        print("polyclient-get-pk_col", pk_col)
        print("polyclient-get-pk_val", pk_val)
        obj = await conn.get(physical_table, pk_col, pk_val)
        return obj

        # ---------------------------------------------------------------------
        # NEW: SQL router  (MVP)
        # ---------------------------------------------------------------------

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

        # The old `query` method can now be deprecated or removed.
        # If kept for backward compatibility,
        # it should be refactored to use `execute`.

    async def query(self, sql: str, *, engine: str = None) -> List:
        """
        (Legacy) Executes a SELECT query.
        For new functionality, prefer the `execute` method.
        """
        # For simplicity, this example will just call the new execute method.
        # In a real scenario, you might add deprecation warnings.
        result = await self.execute(sql, engine=engine)
        return result if isinstance(result, list) else [result]

    async def execute(
        self, sql: str, *, engine: str = None, use_catalogue: bool = False
    ) -> list | dict:
        """
        Parses and executes a SQL query.

        Args:
            sql: The SQL statement to execute.
            use_catalogue: If True, uses the catalogue for routing.
            engine: The target backend. Required if use_catalogue is False.
        """
        if not use_catalogue and not engine:
            msg = (
                "An explicit 'engine' must be provided "
                "when not using the catalogue."  # noqa: F501
            )
            raise ValueError(msg)

        ast = sqlglot.parse_one(sql)

        strategy = self.query_strategies.get(type(ast))

        if not strategy:
            raise NotImplementedError(f"Unsupported query type: {type(ast)}")

        target_backend = engine
        if use_catalogue:
            table_name = ast.find(exp.Table).name.lower()
            catalogue_entry = self._catalogue.get(table_name)
            if not catalogue_entry:
                msg = f"Table '{table_name}' not found in catalogue."
                raise ValueError(msg)

            # Use catalogue's backend, but allow user to override/validate
            catalogue_backend, _ = catalogue_entry
            if engine and engine != catalogue_backend:
                msg = f"Engine override '{engine}' conflicts"
                msg += f" with catalogue backend '{catalogue_backend}'"
                msg += f" for table '{table_name}'."  # noqa: F501
                raise ValueError(msg)
            target_backend = catalogue_backend

        print("polyclient-execute-use_catalogue", use_catalogue)
        print("polyclient-execute-ast", ast.find(exp.Table).name)
        print("polyclient-execute-query", sql)
        if not target_backend:
            # This case should now be unreachable due to the initial check
            raise ValueError("Could not determine target backend.")

        return await strategy.execute(self, ast, target_backend, use_catalogue)
