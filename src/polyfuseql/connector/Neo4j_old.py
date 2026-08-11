# ruff: noqa E501

import csv
import logging
import sys
import asyncio
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, AsyncGenerator

import aiofiles  # Import aiofiles
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncTransaction
from neo4j import time as neo_time
from pydantic import ValidationError
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.Connector import Connector
from polyfuseql.connector.SparkTranslator import SparkTranslator
from polyfuseql.utils.spark_manager import get_spark_session
from polyfuseql.utils.utils import _camelize_keys, get_pydantic_model

logger = logging.getLogger("uvicorn.error")
try:
    from pyspark.sql import functions as F, DataFrame, SparkSession
    from pyspark.sql.types import (
        DateType,
        DecimalType,
        DoubleType,
        StringType,
        IntegerType,
        LongType,
        StructField,
        StructType,
    )

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


def _sanitize_value(value: Any) -> Any:
    """
    Recursively converts Decimal objects to floats to prevent Neo4j driver errors.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


async def _execute_batch_insert(
    tx: AsyncTransaction, query: str, rows: List[Dict]
) -> int:
    """
    Helper function to execute a batch insert within a managed transaction.
    This function is passed to session.execute_write.
    """
    # [FIX] Sanitize rows before passing to driver
    sanitized_rows = _sanitize_value(rows)

    # Neo4j driver handles list of dicts for UNWIND efficiently
    result = await tx.run(query, rows=sanitized_rows)
    summary = await result.consume()
    return summary.counters.nodes_created


class Neo4jConnector(Connector, SparkTranslator):
    """
    Connector for Neo4j with PySpark for efficient aggregations.
    Uses the user-defined schema from the Catalogue.
    """

    def __init__(
        self,
        catalogue: Optional[Catalogue] = None,
        options: Optional[Dict] = None,
    ) -> None:
        super().__init__(options=options, catalogue=catalogue)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            stream=sys.stdout,
        )

        from polyfuseql.config import settings

        self._uri = f"bolt://{settings.neo4j.host}:{settings.neo4j.port}"
        self._auth = (settings.neo4j.user, settings.neo4j.password)
        self._driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        if not self._driver:
            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=self._auth, connection_timeout=600.0
            )
            logging.info("Neo4j driver initialized.")
            # Verify connectivity
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

    async def count(self, entity: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{entity.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    async def get(self, entity: str, pk_col: str, pk_val: Any) -> Dict[str, Any]:
        """
        Fetch a single node by its primary key.
        """
        # [FIX] Sanitize pk_val (e.g. Decimal -> float)
        pk_val = _sanitize_value(pk_val)

        driver = self._get_driver()
        async with driver.session() as s:
            cypher_match = f"MATCH (n:{entity.capitalize()}) "
            cypher_where = f"WHERE n.`{pk_col}` "
            cypher = (
                cypher_match
                + cypher_where
                + "= $pk_val RETURN properties(n) AS p LIMIT 1"
            )
            result = await s.run(cypher, pk_val=pk_val)
            rec = await result.single()
            return rec["p"] if rec and rec["p"] else {}

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        # [FIX] Sanitize payload (e.g. Decimal -> float)
        payload = _sanitize_value(payload)

        driver = self._get_driver()
        props = ", ".join(f"`{k}`: ${k}" for k in payload.keys())

        cypher = f"CREATE (n:{entity.capitalize()} {{ {props} }}) "
        cypher += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher, **payload)
            rec = await result.single()
            return rec["p"] if rec else {}

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        # [FIX] Sanitize inputs
        pk_val = _sanitize_value(pk_val)
        payload = _sanitize_value(payload)

        driver = self._get_driver()
        async with driver.session() as s:
            cypher = f"MATCH (n:{entity.capitalize()} "
            cypher += f"{{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            result = await s.run(cypher, pk_val=pk_val, payload=payload)
            summary = await result.consume()
            return summary.counters.properties_set

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        # [FIX] Sanitize inputs
        pk_val = _sanitize_value(pk_val)

        driver = self._get_driver()
        async with driver.session() as s:
            cypher = (
                f"MATCH (n:{entity.capitalize()} {{{pk_col}: $pk_val}}) "
                "DETACH DELETE n"
            )
            result = await s.run(cypher, pk_val=pk_val)
            summary = await result.consume()
            return summary.counters.nodes_deleted

    async def get_all(
        self,
        entity: str,
        where_clause: Optional[str] = None,
        params: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        # [FIX] Sanitize params for get_all as well
        if params:
            params = _sanitize_value(params)

        driver = self._get_driver()
        cypher_query = f"MATCH (n:{entity.capitalize()}) "
        if where_clause:
            cypher_query += where_clause
        cypher_query += " RETURN properties(n) as p"

        logging.info(f"Executing Cypher: {cypher_query} with params: {params}")

        async with driver.session() as s:
            result = await s.run(cypher_query, **(params or {}))
            return [rec["p"] async for rec in result]

    async def _load_table_to_spark_df(
        self, table_name: str, spark_session
    ) -> "DataFrame":
        """
        [Sonar Refactor] Loads a single table from Neo4j into a Spark DataFrame
        This helper function is called by join(), group_by(), and aggregate()
        to eliminate code duplication.
        """
        label = table_name.capitalize()
        spark_schema = self._get_spark_schema(table_name)

        # 1. Build the Cypher query and read schema
        # We must cast Neo4j's decimals to floats, as the Spark connector
        # has better support for Spark's DoubleType.
        read_schema_fields = []
        return_expressions = []
        date_cols = []  # Track columns that need casting to DateType

        for field in spark_schema.fields:
            if isinstance(field.dataType, (DecimalType, DoubleType)):
                read_schema_fields.append(
                    StructField(field.name, DoubleType(), True)
                )  # noqa:E501
                return_expressions.append(
                    f"toFloat(n.{field.name}) AS {field.name}"
                )  # noqa:E501
            elif isinstance(field.dataType, (IntegerType, LongType)):
                # Keep LongType for IDs/integers to avoid overflow/casting issues
                read_schema_fields.append(StructField(field.name, LongType(), True))
                return_expressions.append(f"toInteger(n.{field.name}) AS {field.name}")
            elif isinstance(field.dataType, DateType):
                # [FIX] Read Dates as Strings first to avoid 'UTF8String
                # cannot be cast to Integer'
                # Spark DateType is internally an int; if we pass a String raw,
                # it crashes.
                read_schema_fields.append(StructField(field.name, StringType(), True))
                return_expressions.append(f"toString(n.{field.name}) AS {field.name}")
                date_cols.append(field.name)
            else:
                read_schema_fields.append(field)
                return_expressions.append(f"n.{field.name} AS {field.name}")

        read_schema = StructType(read_schema_fields)
        label_str = f"MATCH (n:{label})"
        return_str = f"RETURN {', '.join(return_expressions)}"
        cypher_query = f"{label_str} {return_str}"

        # 2. Define the synchronous Spark-loading function
        def _load_sync() -> "DataFrame":
            # try:
            df = (
                spark_session.read.format("org.neo4j.spark.DataSource")
                .option("url", self._uri)
                .option("authentication.type", "basic")
                .option("authentication.basic.username", self._auth[0])
                .option("authentication.basic.password", self._auth[1])
                .option("query", cypher_query)
                .schema(read_schema)
                .load()
            )

            # 3. Cast columns back to their proper types
            for field in spark_schema.fields:
                if isinstance(field.dataType, DecimalType):
                    df = df.withColumn(
                        field.name, F.col(field.name).cast(field.dataType)
                    )

            # [FIX] Explicitly cast String dates to Spark DateType
            for col_name in date_cols:
                df = df.withColumn(col_name, F.col(col_name).cast(DateType()))

            return df
            # except Exception as e:
            #    logging.error(f"Failed to load data using spark-neo4j: {e}")
            #    return spark_session.createDataFrame([], spark_schema)

        # 4. Bridge from async to sync Spark execution
        logging.info(
            f"Loading table '{table_name}' using `spark-neo4j` connector."
        )  # noqa:E501
        df = await asyncio.to_thread(_load_sync)
        return df

    async def _ensure_tables_loaded(
        self, ast: exp.Expression, spark: SparkSession
    ) -> None:
        """
        Identifies all physical tables recursively in the AST and loads them
        into Spark Temp Views. Skips aliases and derived tables (e.g. subqueries)
        that are not defined in the catalogue.
        """
        # find_all(exp.Table) traverses the AST recursively
        for table in ast.find_all(exp.Table):
            table_name = table.name

            # [CRITICAL FIX] Handle case sensitivity for schema lookup.
            # SQLGlot might treat names as uppercase (e.g. PART), but catalogue keys
            # are usually lowercase (e.g. part).
            if not self.catalogue.get_schema(table_name):
                if self.catalogue.get_schema(table_name.lower()):
                    table_name = table_name.lower()
                else:
                    logging.debug(f"Skipping '{table_name}': Not found in catalogue.")
                    continue

            # Skip if already registered to avoid redundant IO
            if spark.catalog.tableExists(table_name):
                continue

            # Load and register the physical table
            df = await self._load_table_to_spark_df(table_name, spark)
            df.createOrReplaceTempView(table_name)

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [New Implementation] Executes a JOIN query using Spark SQL.
        Handles complex joins and subqueries by delegating execution to Spark engine.
        """
        spark = get_spark_session()
        if not spark:
            raise RuntimeError("PySpark is not available for JOINs.")

        # 1. Load all physical tables referenced in the query
        await self._ensure_tables_loaded(ast, spark)

        # 2. Execute the AST directly as Spark SQL
        # This supports subqueries, CTEs, and complex conditions natively
        df = spark.sql(ast.sql())

        results = [row.asDict() for row in df.collect()]
        return [_camelize_keys(row) for row in results]

    # --- ADDED 'query' METHOD ---
    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        """
        Raw SQL queries are not supported. This connector translates SQL,
        but does not execute raw Cypher.
        """
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    # --- ADDED 'group_by' METHOD ---
    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes a GROUP BY query using Spark SQL.
        """
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for GROUP BY operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        # 1. Load all physical tables involved (recursive search)
        await self._ensure_tables_loaded(ast, spark)

        # 2. Run the query via Spark SQL
        # This bypasses manual DataFrame chaining, fixing subquery alias issues
        df = spark.sql(ast.sql())

        results = [row.asDict() for row in df.collect()]
        return [_camelize_keys(row) for row in results]

    # --- ADDED 'aggregate' METHOD ---
    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes an aggregate query using Spark SQL.
        """
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for aggregate operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        # 1. Load tables
        await self._ensure_tables_loaded(ast, spark)

        # 2. Run logic via Spark SQL
        df = spark.sql(ast.sql())

        results = [row.asDict() for row in df.collect()]
        return [_camelize_keys(row) for row in results]

    def _process_row_for_neo4j(
        self, line: List[str], cols: List[str], dynamic_model: Any
    ) -> Optional[Dict[str, Any]]:
        """
        [Sonar Refactor] Processes a single CSV line for Neo4j bulk insert.
        This helper reduces the cognitive complexity of the batch processor.
        Returns a processed dict or None if validation fails or the row is
        empty.
        """
        if not line or len(line) < len(cols):
            return None
        try:
            row_dict = dict(zip(cols, line[: len(cols)]))
            validated_data = dynamic_model(**row_dict)
            model_dict = validated_data.model_dump()

            # Convert types for Neo4j driver
            for key, value in model_dict.items():
                if isinstance(value, date):
                    model_dict[key] = neo_time.Date.from_native(value)
                if isinstance(value, Decimal):
                    model_dict[key] = float(value)

            return model_dict
        except ValidationError as e:
            msg = f"Skipping row due to validation error: {line}. Error: {e}"
            logging.warning(msg)
            return None

    async def _process_csv_batch(
        self,
        file_path: str,
        cols: List[str],
        dynamic_model: Any,
        batch_size: int,
    ) -> AsyncGenerator[List[Dict[str, Any]], None]:
        batch = []
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                lines = [line for line in content.splitlines() if line.strip()]
                reader = csv.reader(lines, delimiter="|")
                for line in reader:
                    # Fix empty trailing column in TPC-H .tbl files
                    if len(line) > len(cols):
                        line = line[: len(cols)]
                    processed_row = self._process_row_for_neo4j(
                        line, cols, dynamic_model
                    )
                    if processed_row:
                        batch.append(processed_row)
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                if batch:
                    yield batch
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> int:
        driver = self._get_driver()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            raise ValueError(f"No schema for: {table_name}")

        cols = list(schema["columns"].keys())
        label = table_name.capitalize()
        dynamic_model = get_pydantic_model(table_name, schema)

        async with driver.session() as s:
            await s.run(f"MATCH (n:{label}) DETACH DELETE n")

        props_str = ", ".join([f"`{c}`: row.`{c}`" for c in cols])
        cypher_query = f"""
        UNWIND $rows AS row
        CREATE (n:{label} {{ {props_str} }})
        """

        total_inserted = 0
        async for batch in self._process_csv_batch(
            file_path, cols, dynamic_model, batch_size
        ):
            if batch:
                # [FIX] Sanitize batch again just in case,
                # though _process_row_for_neo4j handles it.
                # Using _sanitize_value is safer recursively.
                batch = _sanitize_value(batch)

                async with driver.session() as s:
                    nodes_created = await s.execute_write(
                        _execute_batch_insert, cypher_query, batch
                    )
                    total_inserted += nodes_created
        return total_inserted

    def _get_spark_schema(self, table_name: str) -> "StructType":
        sch_def = self.catalogue.get_schema(table_name)
        if not sch_def:
            sch_def = self.catalogue.get_schema(table_name.lower())
        if not sch_def:
            raise ValueError(f"No schema definition for: {table_name}")

        fields = []
        for c_name, c_type_str in sch_def["columns"].items():
            if c_type_str == "date":
                fields.append(StructField(c_name, DateType(), True))
            elif "decimal" in c_type_str:
                # [FIX] Map decimal to DoubleType to allow filter pushdown in Spark
                # without ClientException in Neo4j Connector.
                fields.append(StructField(c_name, DoubleType(), True))
            elif c_type_str == "int":
                # [FIX] Map int to LongType (64-bit)
                fields.append(StructField(c_name, LongType(), True))
            elif c_type_str == "long":
                fields.append(StructField(c_name, LongType(), True))
            elif c_type_str == "float" or c_type_str == "double":
                fields.append(StructField(c_name, DoubleType(), True))
            else:
                fields.append(StructField(c_name, StringType(), True))
        return StructType(fields)
