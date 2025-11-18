"""polyfuseql.client.PolyClient
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unified façade that hides individual datastore connectors.
This update adds a minimal *read‑only* SQL router using **sqlglot**.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Union, Any, Optional, Callable

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
from polyfuseql.connector.Connector import Connector


class PolyClient:
    """Facade that exposes unified helpers plus a tiny SQL router."""

    def __init__(
        self,
        options: Optional[Dict] = None,
        schema_path: Union[str, Path, None] = None,
    ) -> None:
        self.options = options or {}
        self.catalogue = Catalogue(schema_path)

        self._catalogue = self.catalogue  # Keep for backward compatibility

        # 1. Store connection cache (lazily populated)
        self._connections: Dict[str, Connector] = {}

        # 2. Store "factories" for creating connectors
        self._connector_factories: Dict[str, Callable[[], Connector]] = {
            "postgres": lambda: ConnectorFactory.create_connector(
                "postgres", self.catalogue
            ),
            "redis": lambda: ConnectorFactory.create_connector(
                "redis", self.catalogue, self.options
            ),
            "neo4j": lambda: ConnectorFactory.create_connector(
                "neo4j", self.catalogue
            ),  # noqa:E501
            "mongodb": lambda: ConnectorFactory.create_connector(
                "mongodb", self.catalogue
            ),
            "cassandra": lambda: ConnectorFactory.create_connector(
                "cassandra", self.catalogue
            ),
        }

        # Keep alias support
        self._connector_factories["pg"] = self._connector_factories["postgres"]
        self._connector_factories["rd"] = self._connector_factories["redis"]
        self._connector_factories["nj"] = self._connector_factories["neo4j"]

        self.query_strategies = {
            exp.Select: SelectStrategy(),
            exp.Insert: InsertStrategy(),
            exp.Update: UpdateStrategy(),
            exp.Delete: DeleteStrategy(),
            "Join": JoinStrategy(),
        }

    async def get_connector(self, engine: str) -> Connector:
        """
        Lazy-loads a connector.
        Gets from cache or creates, connects, and caches on first call.
        """
        # 3. Check cache first
        conn = self._connections.get(engine)
        if conn:
            conn._options = self.options
            return conn

        # 4. Not in cache, get the factory
        factory = self._connector_factories.get(engine)
        if not factory:
            raise ValueError(f"Unknown connector type: {engine}")

        # 5. Create, connect, and cache the new connector
        logging.info(f"Creating on-demand connection for '{engine}'...")
        conn = factory()
        await conn.connect()
        self._connections[engine] = conn
        conn._options = self.options
        logging.info(f"Connection for '{engine}' established and cached.")
        return conn

    async def close_all_connections(self):
        """Iterates and disconnects all *active* connections."""
        logging.info(f"Closing {len(self._connections)} active connections...")
        disconnect_tasks = [
            conn.disconnect() for conn in self._connections.values()
        ]  # noqa:E501
        await asyncio.gather(*disconnect_tasks)
        self._connections.clear()
        logging.info("All active connections closed.")

    async def __aenter__(self):
        """Establishes connections when entering an `async with` block."""
        # await asyncio.gather(
        #     self.pg.connect(),
        #     self.rd.connect(),
        #     self.nj.connect(),
        #     self.mongo.connect(),
        #     self.cassandra.connect(),
        # )  # noqa:F501
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes connections when exiting an `async with` block."""
        await self.close_all_connections()

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

        conn = await self.get_connector(target_engine)
        if not conn:
            raise ValueError(f"Unknown backend '{target_engine}'")

        logging.info(f"Type conn: {type(conn)}")
        logging.info(f"Table name: {table_name}")
        logging.info(f"Primary key: {target_pk_col}")
        logging.info(f"Primary key value: {primary_key_value}")
        return await conn.get(
            table_name,
            pk_col=str(target_pk_col),
            pk_val=primary_key_value,  # noqa:E501
        )  # noqa:F501

    async def execute(
        self, sql: str, *, engine: str = None, use_catalogue: bool = True
    ) -> Union[List, Dict]:

        if not use_catalogue and not engine:
            raise ValueError(
                "An explicit 'engine' must be provided when not using the catalogue."  # noqa:E501
            )

        ast = sqlglot.parse_one(sql)

        # Determine target backend (logic from your original file)
        target_backend = engine
        if use_catalogue and not target_backend:
            table_name = ast.find(exp.Table).name.lower()
            schema = self.catalogue.get_schema(table_name)
            if not schema:
                raise ValueError(
                    f"Table '{table_name}' not found in catalogue."
                )  # noqa:E501
            target_backend = schema["backend"]

        if not target_backend:
            raise ValueError("Could not determine target backend.")

        # Find the correct strategy to execute
        if isinstance(ast, exp.Select) and ast.find(exp.Join):
            strategy = self.query_strategies["Join"]
        else:
            strategy = self.query_strategies.get(type(ast))

        if not strategy:
            # Handle non-strategy queries (like raw passthrough)
            conn = await self.get_connector(target_backend)  # <-- LAZY LOAD
            result = await conn.query(ast.sql())
            return result if result else []

        # Pass the *backend name* to the strategy, which will then
        # call get_connector() itself.
        return await strategy.execute(self, ast, target_backend, use_catalogue)

    async def bulk_load_table(
        self, table_name: str, file_path: str, engine: str
    ) -> int:
        connector = await self.get_connector(engine)
        logging.info(f"Type connector: {type(connector)}")
        if not connector:
            raise ValueError(f"Unknown engine: {engine}")
        return await connector.bulk_insert(table_name, file_path)
