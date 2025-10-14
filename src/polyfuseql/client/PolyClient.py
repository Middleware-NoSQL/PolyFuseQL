"""polyfuseql.client.PolyClient
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified façade that hides individual datastore connectors.
This update adds a minimal *read‑only* SQL router using **sqlglot**.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Union, Any, Optional

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


class PolyClient:
    """Facade that exposes unified helpers plus a tiny SQL router."""

    def __init__(
        self,
        options: Optional[Dict] = None,
        schema_path: Union[str, Path, None] = None,
    ) -> None:
        self.options = options or {}
        self.catalogue = Catalogue(schema_path)
        self.pg = ConnectorFactory.create_connector("postgres", self.catalogue)
        self.rd = ConnectorFactory.create_connector(
            "redis", self.catalogue, self.options
        )
        self.nj = ConnectorFactory.create_connector("neo4j", self.catalogue)
        self.mongo = ConnectorFactory.create_connector(
            "mongodb", self.catalogue
        )  # noqa:E501
        self.cassandra = ConnectorFactory.create_connector(
            "cassandra", self.catalogue
        )  # noqa:E501
        self._catalogue = self.catalogue  # Keep for backward compatibility
        self.backends = {
            "postgres": self.pg,
            "pg": self.pg,
            "redis": self.rd,
            "neo4j": self.nj,
            "mongodb": self.mongo,
            "cassandra": self.cassandra,
        }
        self.query_strategies = {
            exp.Select: SelectStrategy(),
            exp.Insert: InsertStrategy(),
            exp.Update: UpdateStrategy(),
            exp.Delete: DeleteStrategy(),
            "Join": JoinStrategy(),
        }

    async def __aenter__(self):
        """Establishes connections when entering an `async with` block."""
        await asyncio.gather(
            self.pg.connect(),
            self.rd.connect(),
            self.nj.connect(),
            self.mongo.connect(),
            self.cassandra.connect(),
        )  # noqa:F501
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes connections when exiting an `async with` block."""
        await asyncio.gather(
            self.pg.disconnect(),
            self.rd.disconnect(),
            self.nj.disconnect(),
            self.mongo.disconnect(),
            self.cassandra.disconnect(),
        )

    async def get(
        self,
        table_name: str,
        primary_key_value: Any,
        primary_key_column: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> Dict:
        target_engine = engine
        target_pk_col = primary_key_column

        if not target_engine or not target_pk_col:
            logging.info("Primary key column not found.")
            schema = self._catalogue.get_schema(table_name)
            if schema:
                msg = "Primary key column not found. "
                msg += f"Using default schema : {schema}"
                logging.info(msg)
                if not target_engine:
                    target_engine = schema["backend"]
                if not target_pk_col:
                    target_pk_col = schema["pk"]
                msg = f"target_engine: {target_engine}, "
                msg += f"target_pk_col: {target_pk_col}"
                logging.info(msg)

        if isinstance(target_pk_col, list):
            raise NotImplementedError(
                "Composite primary key GET not supported yet."
            )  # noqa:F501

        if not target_engine:
            msg = (
                f"An 'engine' must be provided, or '{table_name}' must exist "
                "in the catalogue."
            )
            raise ValueError(msg)
        if not target_pk_col:
            msg = "'primary_key_column' must be provided, "
            msg += f"or '{table_name}' must "
            msg += "exist in the catalogue."
            raise ValueError(msg)

        conn = self.backends.get(target_engine)
        if not conn:
            raise ValueError(f"Unknown backend '{target_engine}'")

        logging.info(f"Type conn: {type(conn)}")
        logging.info(f"Table name: {table_name}")
        logging.info(f"Primary key: {target_pk_col}")
        logging.info(f"Primary key value: {primary_key_value}")
        return await conn.get(
            entity=table_name,
            pk_col=str(target_pk_col),
            pk_val=primary_key_value,  # noqa:E501
        )  # noqa:F501

    async def execute(
        self, sql: str, *, engine: str = None, use_catalogue: bool = True
    ) -> Union[List, Dict]:
        if not use_catalogue and not engine:
            msg = "An explicit 'engine' must be provided "
            msg += "when not using the catalogue."
            raise ValueError(msg)

        ast = sqlglot.parse_one(sql)

        if isinstance(ast, exp.Select) and ast.find(exp.Join):
            strategy = self.query_strategies["Join"]
        else:
            strategy = self.query_strategies.get(type(ast))

        if not strategy and self.backends.get(engine).is_local_implementation:
            raise NotImplementedError(f"Unsupported query type: {type(ast)}")
        if (
            not strategy
            and not self.backends.get(engine).is_local_implementation  # noqa:E501
        ):  # noqa:E501
            conn = self.backends.get(engine)
            result = await conn.query(ast.sql())
            return result if result else []

        target_backend = engine
        if use_catalogue and not target_backend:
            table_name = ast.find(exp.Table).name.lower()
            schema = self.catalogue.get_schema(table_name)
            if not schema:
                raise ValueError(
                    f"Table '{table_name}' not found in catalogue."
                )  # noqa:F501
            target_backend = schema["backend"]

        if not target_backend:
            raise ValueError("Could not determine target backend.")

        return await strategy.execute(self, ast, target_backend, use_catalogue)

    async def bulk_load_table(
        self, table_name: str, file_path: str, engine: str
    ) -> int:
        connector = self.backends.get(engine)
        if not connector:
            raise ValueError(f"Unknown engine: {engine}")
        return await connector.bulk_insert(table_name, file_path)
