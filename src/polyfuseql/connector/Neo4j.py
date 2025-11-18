# ruff: noqa E501

import csv
import logging
import sys
import asyncio
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, AsyncGenerator

import aiofiles  # Import aiofiles
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncTransaction
from neo4j import time as neo_time
from pydantic import ValidationError
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.spark_manager import get_spark_session
from polyfuseql.utils.utils import _camelize_keys, get_pydantic_model

try:
    from pyspark.sql import functions as F, DataFrame
    from pyspark.sql.types import (
        DateType,
        DecimalType,
        DoubleType,
        StringType,
        StructField,
        StructType,
    )

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


async def _execute_batch_insert(
    tx: AsyncTransaction, query: str, rows: List[Dict]
) -> int:
    """
    Helper function to execute a batch insert within a managed transaction.
    This function is passed to session.execute_write.
    """
    # Neo4j driver handles list of dicts for UNWIND efficiently
    result = await tx.run(query, rows=rows)
    summary = await result.consume()
    return summary.counters.nodes_created


class Neo4jConnector(Connector):
    """
    Connector for Neo4j with PySpark for efficient aggregations.
    Uses the user-defined schema from the Catalogue.
    """

    async def count(self, entity: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{entity.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    def __init__(
        self,
        catalogue: Optional[Catalogue] = None,
        options: Optional[Dict] = None,  # noqa:E501
    ) -> None:
        super().__init__(options=options, catalogue=catalogue)
        from polyfuseql.config import settings

        self._uri = f"bolt://{settings.neo4j.host}:{settings.neo4j.port}"
        self._user = settings.neo4j.user
        self._password = settings.neo4j.password
        self._database = "neo4j"
        self._driver: Optional[AsyncDriver] = None

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            stream=sys.stdout,
        )

    async def connect(self) -> None:
        if not self._driver:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                connection_timeout=600.0,  # noqa:E501
            )
            logging.info("Neo4j driver initialized.")

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logging.info("Neo4j driver closed.")

    def _get_driver(self) -> AsyncDriver:
        if not self._driver:
            # Auto-connect if driver is missing
            # (common pattern in other connectors)
            # However, since connect is async, we can't await it here easily
            # without changing signature.
            # For robustness, we assume the client calls connect(),
            # or we raise error.
            raise ConnectionError(
                "Neo4jConnector is not connected. Call connect() first."
            )
        return self._driver

    async def ping(self) -> bool:
        if not self._driver:
            return False
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    # --- [FIX] Parameter Sanitization Helper ---
    @staticmethod
    def _sanitize_value(value: Any) -> Any:
        """
        Converts types not supported by Neo4j driver (like Decimal)
        into supported types (int, float, str).
        """
        if isinstance(value, Decimal):
            # Convert to int if it's a whole number, else float
            if value % 1 == 0:
                return int(value)
            return float(value)
        if isinstance(value, dict):
            return {
                k: Neo4jConnector._sanitize_value(v) for k, v in value.items()
            }  # noqa:E501
        if isinstance(value, list):
            return [Neo4jConnector._sanitize_value(v) for v in value]
        return value

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa:E501
        driver = self._get_driver()

        # [FIX] Sanitize pk_val (convert Decimal -> int/float)
        safe_pk_val = self._sanitize_value(pk_val)

        query = f"MATCH (n:{entity.capitalize()}) "
        query += f"WHERE n.{pk_col} = $pk_val "
        query += "RETURN properties(n) as p"

        async with driver.session(database=self._database) as s:
            result = await s.run(query, pk_val=safe_pk_val)
            record = await result.single()
            if record:
                data = record["p"]
                # Convert Neo4j types (like neo4j.time.Date)
                # back to Python types if needed
                # Handle date objects for consistency
                for k, v in data.items():
                    if isinstance(v, neo_time.Date):
                        data[k] = date(v.year, v.month, v.day)
                return _camelize_keys(data)
        return {}

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        driver = self._get_driver()

        # [FIX] Sanitize payload
        safe_payload = self._sanitize_value(payload)

        # Construct Cypher query
        # "CREATE (n:Table $props)"
        query = f"CREATE (n:{entity.capitalize()} $props) "
        query += "RETURN properties(n) as p"
        async with driver.session(database=self._database) as s:
            result = await s.run(query, props=safe_payload)
            record = await result.single()
            if record:
                return record["p"]
        return {}

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        driver = self._get_driver()

        # [FIX] Sanitize inputs
        safe_pk_val = self._sanitize_value(pk_val)
        safe_payload = self._sanitize_value(payload)

        # Construct Cypher SET clause dynamically is tricky
        # with parameter map directly
        # Better to use += operator for map update in Cypher
        query = (
            f"MATCH (n:{entity.capitalize()}) WHERE n.{pk_col} = $pk_val "
            f"SET n += $payload RETURN count(n) as updated_count"
        )

        async with driver.session(database=self._database) as s:
            result = await s.run(
                query, pk_val=safe_pk_val, payload=safe_payload
            )  # noqa:E501
            summary = await result.consume()
            # summary.counters.properties_set is more accurate for updates
            return summary.counters.properties_set

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        driver = self._get_driver()

        # [FIX] Sanitize pk_val
        safe_pk_val = self._sanitize_value(pk_val)

        query = f"MATCH (n:{entity.capitalize()}) "
        query += f"WHERE n.{pk_col} = $pk_val "
        query += "DETACH DELETE n"

        async with driver.session(database=self._database) as s:
            result = await s.run(query, pk_val=safe_pk_val)
            summary = await result.consume()
            return summary.counters.nodes_deleted

    async def get_all(
        self,
        entity: str,
        where_clause: Optional[str] = None,
        params: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        driver = self._get_driver()

        # [FIX] Sanitize params if they exist
        safe_params = self._sanitize_value(params) if params else {}

        cypher_query = f"MATCH (n:{entity.capitalize()}) "
        if where_clause:
            cypher_query += where_clause
        cypher_query += " RETURN properties(n) as p"

        msg = f"Executing Cypher: {cypher_query} "
        msg += f"with params: {safe_params}"
        logging.info(msg)
        results = []
        async with driver.session(database=self._database) as s:
            result = await s.run(cypher_query, **safe_params)
            async for record in result:
                node = record["p"]
                # Basic type conversion
                for k, v in node.items():
                    if isinstance(v, neo_time.Date):
                        node[k] = date(v.year, v.month, v.day)
                results.append(_camelize_keys(node))
        return results

    # --- Bulk Insert Refactoring ---

    def _process_row_for_neo4j(
        self, line: List[str], cols: List[str], dynamic_model: Any
    ) -> Optional[Dict[str, Any]]:
        """
        [Sonar Refactor] Processes a single CSV line for Neo4j bulk insert.
        This helper reduces the cognitive complexity of the batch processor.
        Returns a processed dict or None if validation fails or
         the row is empty.
        """
        if not line or len(line) < len(cols):
            return None
        try:
            row_dict = dict(zip(cols, line[: len(cols)]))
            validated_data = dynamic_model(**row_dict)
            model_dict = validated_data.model_dump()

            # [CRITICAL FIX] Convert types for Neo4j driver using sanitize
            # This handles Decimals (converting to float/int)
            sanitized_dict = self._sanitize_value(model_dict)

            # Handle date objects specifically for Neo4j driver compatibility
            for key, value in sanitized_dict.items():
                if isinstance(value, date) and not isinstance(
                    value, neo_time.Date
                ):  # noqa:E501
                    sanitized_dict[key] = neo_time.Date.from_native(value)

            return sanitized_dict
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
        """
        [Sonar Refactor] Asynchronously reads a CSV file, validates rows,
        and yields batches of processed data.
        Fixes S3776 (Cognitive Complexity) and S7493 (Async file I/O).
        """
        batch = []
        try:
            # [FIX] Use aiofiles correctly with splitlines()
            # as per Postgres fix
            async with aiofiles.open(
                file_path, "r", encoding="utf-8"
            ) as f:  # noqa:E501
                content = await f.read()
                reader = csv.reader(content.splitlines(), delimiter="|")

                for line in reader:
                    # TPC-H trailing delimiter check
                    if line and line[-1] == "":
                        line = line[:-1]

                    # Delegate row processing to the new helper function
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
        except Exception as e:
            logging.error(f"Error during CSV processing for {file_path}: {e}")
            raise

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> int:
        """
        Bulk inserts data from a file into the specified table.
        This function has been refactored to reduce cognitive complexity
        by delegating row processing to `_process_csv_batch`.
        """
        driver = self._get_driver()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            msg = f"No schema definition found for table: {table_name}"
            raise ValueError(msg)

        cols = list(schema["columns"].keys())
        label = table_name.capitalize()
        dynamic_model = get_pydantic_model(table_name, schema)

        # Clear the table first
        async with driver.session() as s:
            await s.run(f"MATCH (n:{label}) DETACH DELETE n")

        # Prepare the Cypher query
        props_str = ", ".join([f"`{c}`: row.`{c}`" for c in cols])
        cypher_query = f"""
        UNWIND $rows AS row
        CREATE (n:{label} {{ {props_str} }})
        """

        total_inserted = 0
        # Use the async generator to process batches
        async for batch in self._process_csv_batch(
            file_path, cols, dynamic_model, batch_size
        ):
            if batch:
                async with driver.session() as s:
                    nodes_created = await s.execute_write(
                        _execute_batch_insert, cypher_query, batch
                    )
                    total_inserted += nodes_created

        return total_inserted

    # --- PySpark Integration for Joins/Aggregations ---

    def _get_spark_schema(self, table_name: str) -> "StructType":
        sch_def = self.catalogue.get_schema(table_name)
        if not sch_def:
            msg = "No schema definition found for table: "
            msg += f"{table_name}"
            raise ValueError(msg)
        fields = []
        for c_name, c_type_str in sch_def["columns"].items():
            if c_type_str == "date":
                fields.append(StructField(c_name, DateType(), True))
            elif "decimal" in c_type_str:
                fields.append(
                    StructField(c_name, DecimalType(38, 10), True)
                )  # noqa:F501
            else:
                fields.append(StructField(c_name, StringType(), True))
        return StructType(fields)

    async def _load_table_to_spark_df(
        self, table_name: str, spark_session
    ) -> "DataFrame":
        """
        Loads a single table from Neo4j into a Spark DataFrame.
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
        for field in spark_schema.fields:
            if isinstance(field.dataType, (DecimalType, DoubleType)):
                read_schema_fields.append(
                    StructField(field.name, DoubleType(), True)
                )  # noqa:E501
                return_expressions.append(
                    f"toFloat(n.{field.name}) AS {field.name}"
                )  # noqa:E501
            else:
                read_schema_fields.append(field)
                return_expressions.append(f"n.{field.name} AS {field.name}")
        read_schema = StructType(read_schema_fields)
        cypher_query = f"MATCH (n:{label}) "
        cypher_query += f"RETURN {', '.join(return_expressions)}"

        # 2. Define the synchronous Spark-loading function
        def _load_sync() -> "DataFrame":
            try:
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

                # 3. Cast columns back to their proper high-precision types
                for field in spark_schema.fields:
                    if isinstance(field.dataType, DecimalType):
                        df = df.withColumn(
                            field.name, F.col(field.name).cast(field.dataType)
                        )
                return df
            except Exception as e:
                logging.error(f"Failed to load data using spark-neo4j: {e}")
                return spark_session.createDataFrame([], spark_schema)

        # 4. Bridge from async to sync Spark execution
        msg = f"Loading table '{table_name}' "
        msg += "using `spark-neo4j` connector."
        logging.info(msg)
        df = await asyncio.to_thread(_load_sync)
        return df

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [New Implementation] Executes a JOIN query using Spark.
        Delegates data loading to _load_table_to_spark_df.
        """
        spark = get_spark_session()
        if not spark:
            raise RuntimeError("PySpark is not available for JOINs.")

        # 1. Fetch the FROM table
        from_table_expr = ast.args.get("from").this
        from_table_name = from_table_expr.this.name
        from_table_alias = from_table_expr.alias_or_name

        joined_df = (
            await self._load_table_to_spark_df(from_table_name, spark)
        ).alias(  # noqa:E501
            from_table_alias
        )

        # 2. Loop through JOINs
        joins = ast.args.get("joins", [])
        for join_expr in joins:
            join_table_expr = join_expr.this
            join_table_name = join_table_expr.this.name
            join_table_alias = join_table_expr.alias_or_name

            df_to_join = (
                await self._load_table_to_spark_df(join_table_name, spark)
            ).alias(join_table_alias)

            join_condition = self._translate_expression_to_spark(
                join_expr.args.get("on")
            )
            join_type = join_expr.args.get("kind", "INNER").lower()

            joined_df = joined_df.join(
                df_to_join, on=join_condition, how=join_type
            )  # noqa:E501

        # 3. Apply WHERE
        if ast.args.get("where"):
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa:E501
            joined_df = joined_df.filter(filter_cond)

        # 4. Apply SELECT
        select_expressions = [
            self._translate_expression_to_spark(e) for e in ast.expressions
        ]
        final_df = joined_df.select(*select_expressions)

        # 5. Apply ORDER BY
        if ast.args.get("order"):
            order_exprs = []
            for e in ast.args["order"].expressions:
                col = self._translate_expression_to_spark(e.this)
                direction = e.args.get("desc", False)
                order_exprs.append(col.desc() if direction else col.asc())
            final_df = final_df.orderBy(*order_exprs)

        # 6. Apply LIMIT
        if ast.args.get("limit"):
            limit_val = int(ast.args["limit"].this.this)
            final_df = final_df.limit(limit_val)

        # 7. Collect and return
        results = [row.asDict() for row in final_df.collect()]
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
        [Sonar Refactor] Executes a GROUP BY query using Spark.
        This method now delegates data loading to _load_table_to_spark_df.
        """
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for GROUP BY operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        # 1. Load the data using the refactored helper
        table_name = ast.find(exp.Table).name
        df = await self._load_table_to_spark_df(table_name, spark)

        if df.isEmpty():
            return []

        # 2. Apply WHERE
        if ast.args.get("where"):
            # Use the robust Spark filter, not Cypher string manipulation
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa:E501
            df = df.filter(filter_cond)

        # 3. Apply GROUP BY
        group_by_cols = [
            self._translate_expression_to_spark(e)
            for e in ast.args.get("group").expressions
        ]
        grouped_df = df.groupBy(*group_by_cols)

        # 4. Apply Aggregations
        agg_expressions = []
        final_cols = []
        for expr in ast.expressions:
            spark_expr = self._translate_expression_to_spark(expr)
            agg_expressions.append(spark_expr)
            final_cols.append(expr.alias_or_name)

        agg_df = grouped_df.agg(*agg_expressions)

        # 5. Apply ORDER BY
        if ast.args.get("order"):
            order_cols = []
            for e in ast.args["order"].expressions:
                col = self._translate_expression_to_spark(e.this)
                direction = e.args.get("desc", False)
                order_cols.append(col.desc() if direction else col.asc())
            agg_df = agg_df.orderBy(*order_cols)

        # 6. Apply SELECT (final projection)
        final_df = agg_df.select(*final_cols)
        results = [row.asDict() for row in final_df.collect()]
        return [_camelize_keys(row) for row in results]

    # --- ADDED 'aggregate' METHOD ---
    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes an aggregate query using Spark.
        This method now delegates data loading to _load_table_to_spark_df.
        """
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for aggregate operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        # 1. Load the data
        table_name = ast.find(exp.Table).name
        df = await self._load_table_to_spark_df(table_name, spark)

        if df.isEmpty():
            # Return a default empty/zero state if no data
            result = {}
            for expr in ast.expressions:
                alias = expr.alias_or_name
                result[alias] = (
                    Decimal("0.0")
                    if isinstance(expr.this, (exp.Sum, exp.Avg))
                    else 0  # noqa:E501
                )
            return [_camelize_keys(result)]

        # 2. Apply WHERE
        if ast.args.get("where"):
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa:E501
            df = df.filter(filter_cond)

        # 3. Apply Aggregations
        agg_expressions = []
        for expr in ast.expressions:
            spark_expr = self._translate_expression_to_spark(expr)
            agg_expressions.append(spark_expr)

        result_df = df.agg(*agg_expressions)
        results = [row.asDict() for row in result_df.collect()]

        return [_camelize_keys(row) for row in results]

    # --- [SONARQUBE S3776 FIX] ---
    # The following methods refactor _translate_expression_to_spark
    # to reduce Cognitive Complexity from 22 to a much lower number.

    def _translate_alias(self, expression: exp.Alias):
        """Translates an ALIAS expression (e.g., col AS c)."""
        inner_expr = self._translate_expression_to_spark(expression.this)
        return inner_expr.alias(expression.alias)

    def _translate_column(self, expression: exp.Column):
        """Translates a COLUMN expression (e.g., t1.col or col)."""
        if expression.table:
            return F.col(f"{expression.table}.{expression.name}")
        return F.col(expression.name)

    def _translate_literal(self, expression: exp.Literal):
        """Translates a LITERAL expression (e.g., 'foo', 123, 12.5)."""
        val = expression.this
        try:
            # Try to cast to Decimal for numeric literals
            return (
                F.lit(Decimal(val)) if not expression.is_string else F.lit(val)
            )  # noqa:E501
        except InvalidOperation:
            # Fallback to string literal
            return F.lit(val)

    def _translate_paren(self, expression: exp.Paren):
        """Translates a PAREN expression (e.g., (1 + 1))."""
        return self._translate_expression_to_spark(expression.this)

    def _translate_binary(self, expression: exp.Binary):
        """Translates all BINARY expressions (e.g., +, -, =, AND, OR)."""
        left = self._translate_expression_to_spark(expression.left)
        right = self._translate_expression_to_spark(expression.right)

        # Using a map is cleaner than a large if/elif block
        op_map = {
            exp.Mul: lambda a, b: a * b,
            exp.Sub: lambda a, b: a - b,
            exp.Add: lambda a, b: a + b,
            exp.Div: lambda a, b: a / b,
            exp.EQ: lambda a, b: a == b,
            exp.NEQ: lambda a, b: a != b,
            exp.GT: lambda a, b: a > b,
            exp.GTE: lambda a, b: a >= b,
            exp.LT: lambda a, b: a < b,
            exp.LTE: lambda a, b: a <= b,
            exp.And: lambda a, b: a & b,
            exp.Or: lambda a, b: a | b,
        }

        op_func = op_map.get(type(expression))
        if op_func:
            return op_func(left, right)

        raise NotImplementedError(
            f"Unsupported binary operator: {type(expression)}"
        )  # noqa:E501

    def _translate_agg_func(self, expression: exp.AggFunc):
        """Translates all AGGREGATE expressions (e.g., SUM, COUNT)."""
        inner_expr = self._translate_expression_to_spark(expression.this)

        agg_map = {
            exp.Sum: F.sum,
            exp.Avg: F.avg,
            exp.Count: F.count,
            exp.Min: F.min,
            exp.Max: F.max,
        }

        agg_func = agg_map.get(type(expression))
        if not agg_func:
            raise NotImplementedError(
                f"Unsupported aggregate function: {type(expression)}"
            )

        agg_expr = agg_func(inner_expr)
        if type(expression) in [exp.Sum, exp.Avg]:
            # Cast aggregates to a high-precision decimal
            agg_expr = agg_expr.cast(DecimalType(38, 6))

        return agg_expr

    def _translate_cast(self, expression: exp.Cast):
        """Translates a CAST expression (e.g., CAST(col AS DATE))."""
        if expression.to.this == exp.DataType.Type.DATE:
            return F.to_date(
                self._translate_expression_to_spark(expression.this)
            )  # noqa:E501

        raise NotImplementedError(
            f"Unsupported CAST type: {expression.to.this}"
        )  # noqa:E501

    def _translate_star(self, expression: exp.Star):
        """Translates a STAR expression (e.g., COUNT(*))."""
        return F.lit(1)

    def _translate_expression_to_spark(self, expression: exp.Expression):
        """
        [Sonar Refactor]
        Translates a sqlglot Expression into a PySpark Column expression.
        Delegates to helper methods to reduce cognitive complexity.
        """
        # --- Dispatcher ---
        # We check base classes first (Binary, AggFunc)
        # before checking specific concrete types.

        if isinstance(expression, exp.Binary):
            return self._translate_binary(expression)

        if isinstance(expression, exp.AggFunc):
            return self._translate_agg_func(expression)

        translator_map = {
            exp.Alias: self._translate_alias,
            exp.Column: self._translate_column,
            exp.Literal: self._translate_literal,
            exp.Paren: self._translate_paren,
            exp.Cast: self._translate_cast,
            exp.Star: self._translate_star,
        }

        translator = translator_map.get(type(expression))

        if translator:
            return translator(expression)

        msg = "Unsupported SQL expression for Spark translation: "
        msg += f"{type(expression)}"
        raise NotImplementedError(msg)
