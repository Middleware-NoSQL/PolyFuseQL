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
from typing import Dict, List, Tuple, Union, Sequence, Any, Optional

__all__ = [
    "PolyClient",
]

import sqlglot
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.ConnectorFactory import ConnectorFactory
from polyfuseql.strategy.Delete import DeleteStrategy
from polyfuseql.strategy.Insert import InsertStrategy
from polyfuseql.strategy.Join import JoinStrategy
from polyfuseql.strategy.Select import SelectStrategy
from polyfuseql.strategy.Update import UpdateStrategy

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
            exp.Update: UpdateStrategy(),
            exp.Delete: DeleteStrategy(),
            "Join": JoinStrategy(),
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
        logging.info(backend, source)
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
        self,
        table_name: str,
        primary_key_value: Any,
        primary_key_column: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> Dict:
        """
        Fetches a single record by its primary key.

        This method can operate in two modes:
        1.  **Direct Mode**: Provide 'engine' and 'primary_key_column' to query
            a backend directly without relying on the catalogue.
        2.  **Catalogue-Assisted Mode**: Omit 'engine'
            and/or 'primary_key_column'
            to look up the missing information from the catalogue.

        Args:
            table_name: The name of the table or entity.
            primary_key_value: The value of the primary key to find.
            primary_key_column: (Optional) The name of the primary key column.
            engine: (Optional) The database engine to target.

        Returns:
            A dictionary representing the record, or an
            empty dict if not found.
        """
        target_engine = engine
        target_pk_col = primary_key_column

        # Use the catalogue as a fallback if information is missing
        if not target_engine or not target_pk_col:
            catalogue_entry = self._catalogue.get(table_name.lower())
            if catalogue_entry:
                # Fill in missing details from the catalogue
                if not target_engine:
                    target_engine = catalogue_entry[0]
                if not target_pk_col:
                    target_pk_col = catalogue_entry[1]

        # Final validation to ensure we have all necessary information
        if not target_engine:
            msg = "An 'engine' must be provided, or "
            msg += f"'{table_name}' must exist in the catalogue."
            raise ValueError(msg)
        if not target_pk_col:
            msg = "'primary_key_column' must be provided, or "
            msg += f"'{table_name}' must exist in the catalogue."
            raise ValueError(msg)

        conn = self.backends.get(target_engine)
        if not conn:
            raise ValueError(f"Unknown backend '{target_engine}'")

        # The physical table name is provided directly by the user.
        # The connector's .get() method is already
        # clean and requires these three arguments.
        return await conn.get(table_name, target_pk_col, primary_key_value)

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

        # Determine which strategy to use based on the query structure
        if isinstance(ast, exp.Select) and ast.find(exp.Join):
            strategy = self.query_strategies["Join"]
        else:
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

        logging.info("polyclient-execute-use_catalogue", use_catalogue)
        logging.info("polyclient-execute-ast", ast.find(exp.Table).name)
        logging.info("polyclient-execute-query", sql)
        logging.info("polyclient-execute-strategy", str(strategy.__class__))
        if not target_backend:
            # This case should now be unreachable due to the initial check
            raise ValueError("Could not determine target backend.")

        return await strategy.execute(self, ast, target_backend, use_catalogue)
