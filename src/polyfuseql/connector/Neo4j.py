# ruff: noqa E501

import csv
import logging
import sys
import asyncio  # Import asyncio for thread bridging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

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
    result = await tx.run(query, rows=rows)
    summary = await result.consume()
    return summary.counters.nodes_created


class Neo4jConnector(Connector):
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

        self._uri = f"bolt://{settings.neo4j.host}:" f"{settings.neo4j.port}"
        self._auth = (settings.neo4j.user, settings.neo4j.password)
        self._driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        if not self._driver:
            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=self._auth, connection_timeout=600.0
            )
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

    async def count(self, entity: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{entity.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa:F501
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
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = f"MATCH (n:{entity.capitalize()} "
            cypher += f"{{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            result = await s.run(cypher, pk_val=pk_val, payload=payload)
            summary = await result.consume()
            return summary.counters.properties_set

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
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
        cypher_query = (
            f"MATCH (n:{label}) RETURN {', '.join(return_expressions)}"  # noqa:E501
        )

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
        logging.info(
            f"Loading table '{table_name}' using `spark-neo4j` connector."
        )  # noqa:E501
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
        )  # noqa:E501

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

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

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

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> int:
        driver = self._get_driver()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            msg = "No schema definition found for table: "
            msg += f"{table_name}"
            raise ValueError(msg)

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
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")
                batch = []
                for line in reader:
                    if not line or len(line) < len(cols):
                        continue
                    try:
                        row_dict = dict(zip(cols, line[: len(cols)]))
                        validated_data = dynamic_model(**row_dict)
                        model_dict = validated_data.model_dump()

                        for key, value in model_dict.items():
                            if isinstance(value, date):
                                model_dict[key] = neo_time.Date.from_native(
                                    value
                                )  # noqa:F501
                            if isinstance(value, Decimal):
                                model_dict[key] = float(value)

                        batch.append(model_dict)
                    except ValidationError as e:
                        msg = "Skipping row due to validation "
                        msg += f"error: {line}. Error: {e}"
                        logging.warning(msg)
                        continue

                    if len(batch) >= batch_size:
                        async with driver.session() as s:
                            nodes_created = await s.execute_write(
                                _execute_batch_insert, cypher_query, batch  # noqa
                            )
                            total_inserted += nodes_created
                        batch = []

                if batch:
                    async with driver.session() as s:
                        nodes_created = await s.execute_write(
                            _execute_batch_insert, cypher_query, batch
                        )
                        total_inserted += nodes_created
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Error during bulk insert for {table_name}: {e}")
            raise
        return total_inserted

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

    def _translate_expression_to_spark(self, expression: exp.Expression):
        """
        [Upgraded Implementation]
        Translates a sqlglot Expression into a PySpark Column expression.
        """
        if isinstance(expression, exp.Alias):
            # Handle alias, but recurse on the aliased expression
            inner_expr = self._translate_expression_to_spark(expression.this)
            return inner_expr.alias(expression.alias)

        if isinstance(expression, exp.Column):
            # Handle qualified columns like t1.c_custkey
            if expression.table:
                return F.col(f"{expression.table}.{expression.name}")
            return F.col(expression.name)

        if isinstance(expression, exp.Literal):
            val = expression.this
            try:
                # Try to cast to Decimal for numeric literals
                return (
                    F.lit(Decimal(val))
                    if not expression.is_string
                    else F.lit(val)  # noqa:E501
                )  # noqa:E501
            except InvalidOperation:
                # Fallback to string literal
                return F.lit(val)

        if isinstance(expression, exp.Paren):
            return self._translate_expression_to_spark(expression.this)

        # Binary operations (e.g., in JOINs or WHERE)
        if isinstance(expression, exp.Binary):
            left = self._translate_expression_to_spark(expression.left)
            right = self._translate_expression_to_spark(expression.right)
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
            if type(expression) in op_map:
                return op_map[type(expression)](left, right)

        # Aggregate Functions
        if isinstance(expression, exp.AggFunc):
            inner_expr = self._translate_expression_to_spark(expression.this)
            agg_map = {
                exp.Sum: F.sum,
                exp.Avg: F.avg,
                exp.Count: F.count,
                exp.Min: F.min,
                exp.Max: F.max,
            }
            if type(expression) in agg_map:
                agg_expr = agg_map[type(expression)](inner_expr)
                if type(expression) in [exp.Sum, exp.Avg]:
                    # Cast aggregates to a high-precision decimal
                    agg_expr = agg_expr.cast(DecimalType(38, 6))
                return agg_expr

        if (
            isinstance(expression, exp.Cast)
            and expression.to.this == exp.DataType.Type.DATE
        ):
            return F.to_date(
                self._translate_expression_to_spark(expression.this)
            )  # noqa:E501

        if isinstance(expression, exp.Star):
            return F.lit(1)

        raise NotImplementedError(
            f"Unsupported SQL expression for Spark translation: {type(expression)}"  # noqa:E501
        )
