import csv
import logging
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from neo4j import AsyncDriver
from neo4j import AsyncGraphDatabase as AGD
from neo4j import time as neo_time
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
from polyfuseql.utils.utils import _camelize_keys, env, get_pydantic_model
from pydantic import ValidationError
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    StructField,
    StructType,
    StringType,
)
from sqlglot import exp


class Neo4jConnector(Connector):
    """
    Connector for Neo4j with PySpark for efficient aggregations.

    IMPROVEMENT: This version has been modified to push down filters to Neo4j,
    drastically reducing the amount of data transferred to Spark.
    """

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)

        # --- SOLUTION: Add proper logging setup ---
        # This will ensure all logs are printed to the
        # console during pytest runs
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            stream=sys.stdout,
        )

        host = env("NEO4J_HOST", "localhost")
        port = env("NEO4J_PORT", "7687")
        user = env("NEO4J_USER", "neo4j")
        password = env("NEO4J_PASSWORD", "password")
        self._uri = f"bolt://{host}:{port}"
        self._auth = (user, password)
        self._driver: Optional[AsyncDriver] = None

        # spark_master_url = "spark://cuscungo:7077"
        spark_master_url = "local[*]"
        if "local" not in spark_master_url:
            builder = (
                SparkSession.builder.appName("Neo4jConnector-TPCH-Benchmark")
                .master(spark_master_url)
                .config("spark.cores.max", "48")
                .config("spark.driver.memory", "4g")
                .config("spark.executor.memory", "3g")
                .config("spark.sql.shuffle.partitions", "144")
                # --- SOLUTION: Increase network timeouts for
                # long-running jobs ---
                # Increase the network timeout to 8000 seconds (~133 minutes)
                .config("spark.network.timeout", "8000s")
                # Ensure executors send heartbeats frequently to stay alive
                .config("spark.executor.heartbeatInterval", "60s")
                .config(
                    "spark.jars.packages",
                    "org.neo4j:neo4j-connector-apache-spark_2.12:5.2.0",
                )
            )
        else:
            builder = (
                SparkSession.builder.appName("RedisConnector")
                .master(spark_master_url)
                .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
            )
            # Default memory for local mode
            builder = builder.config("spark.driver.memory", "4g")

        self.spark = builder.getOrCreate()
        msg = "Spark session initialized and connected to "
        msg += f"master: {spark_master_url}"
        logging.info(msg)
        msg1 = "Spark UI available "
        msg1 += f"at: {self.spark.sparkContext.uiWebUrl}"
        logging.info(msg1)

    async def connect(self) -> None:
        if not self._driver:
            # Increased timeout
            self._driver = AGD.driver(
                self._uri, auth=self._auth, connection_timeout=600.0
            )
            logging.info("Neo4j driver initialized.")
            await self.ping()

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logging.info("Neo4j driver closed.")
        if self.spark:
            self.spark.stop()
            logging.info("Spark session stopped.")

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
        """
        Fetches data from Neo4j.

        IMPROVEMENT: Now accepts an optional 'where_clause' and 'params'
        to filter data at the database level.
        """
        driver = self._get_driver()
        cypher_query = f"MATCH (n:{entity.capitalize()}) "
        if where_clause:
            cypher_query += where_clause
        cypher_query += " RETURN properties(n) as p"

        logging.info(f"Executing Cypher: {cypher_query} with params: {params}")

        async with driver.session() as s:
            result = await s.run(cypher_query, **(params or {}))
            return [rec["p"] async for rec in result]

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Manually translates a SQL JOIN AST to a Cypher query."""
        # This is a simplified implementation for demonstration.
        # A more robust solution would require a comprehensive
        # SQL-to-Cypher translator.
        msg = "JOIN is not fully implemented for Neo4j connector."
        raise NotImplementedError(msg)

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    def _translate_where_to_cypher(
        self, where_expr: exp.Expression
    ) -> tuple[str, dict]:
        """
        Translates a sqlglot WHERE expression into a Cypher WHERE clause and
        parameters. This is a simplified translator for TPC-H Query 1.
        """
        if isinstance(where_expr, exp.LTE):
            col_name = where_expr.left.sql()
            param_name = "where_param"

            # Handle date literal
            is_cast = isinstance(where_expr.right, exp.Cast)
            is_date = where_expr.right.to.this == exp.DataType.Type.DATE
            if is_cast and is_date:
                date_str = where_expr.right.this.this
                param_value = neo_time.Date.from_iso_format(date_str)
                cypher_clause = f"WHERE n.{col_name} <= ${param_name}"
                return cypher_clause, {param_name: param_value}

        msg = f"Unsupported WHERE for Cypher translation: {type(where_expr)}"
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        Performs a GROUP BY operation using PySpark.

        IMPROVEMENT: Filters data in Neo4j *before* fetching it.
        """
        table_name = ast.find(exp.Table).name

        cypher_where_clause = None
        params = {}

        if ast.args.get("where"):
            where_this = ast.args["where"].this
            cypher_where_clause, params = self._translate_where_to_cypher(
                where_this
            )  # noqa:F501

        all_data = await self.get_all(
            table_name, where_clause=cypher_where_clause, params=params
        )

        if not all_data:
            return []

        schema_def = TPCH_SCHEMA.get(table_name.lower(), {})
        decimal_cols = {
            col
            for col, type_str in zip(
                schema_def.get("columns", []), schema_def.get("types", [])
            )
            if "decimal" in type_str
        }

        for row in all_data:
            for key, value in row.items():
                if isinstance(value, neo_time.Date):
                    row[key] = date(value.year, value.month, value.day)
                elif key in decimal_cols and isinstance(value, (float, int)):
                    row[key] = Decimal(str(value))

        spark_schema = self._get_spark_schema(table_name)
        df = self.spark.createDataFrame(all_data, schema=spark_schema)

        group_by_cols = [e.sql() for e in ast.args.get("group").expressions]

        agg_expressions = []
        for expr in ast.expressions:
            alias = expr.alias_or_name
            if isinstance(expr, exp.Column):
                continue

            if isinstance(expr, exp.Alias):
                agg_func = expr.this
                spark_col_expr = self._translate_expression_to_spark(
                    agg_func.this
                )  # noqa:F501

                is_col = isinstance(agg_func.this, (exp.Column, exp.Star))
                if not is_col:
                    spark_col_expr = spark_col_expr.cast(DecimalType(38, 10))

                if isinstance(agg_func, exp.Count):
                    agg_expressions.append(
                        F.count(spark_col_expr).alias(alias)
                    )  # noqa:F501
                elif isinstance(agg_func, exp.Sum):
                    agg_expressions.append(F.sum(spark_col_expr).alias(alias))
                elif isinstance(agg_func, exp.Avg):
                    agg_expressions.append(F.avg(spark_col_expr).alias(alias))

        result_df = df.groupBy(*group_by_cols).agg(*agg_expressions)

        if ast.args.get("order"):
            order_by_cols = []
            for ob in ast.args["order"].expressions:
                col_name = ob.this.sql()
                if ob.args.get("desc", False):
                    order_by_cols.append(F.col(col_name).desc())
                else:
                    order_by_cols.append(F.col(col_name).asc())
            result_df = result_df.orderBy(*order_by_cols)

        select_cols = [e.alias_or_name for e in ast.expressions]
        result_df = result_df.select(*select_cols)

        logging.info("Spark job starting collection...")
        results = [row.asDict() for row in result_df.collect()]
        logging.info("Spark job collection finished.")
        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Performs aggregation using PySpark."""
        table_name = ast.find(exp.Table).name
        # The schema for 'sales' is not in TPCH_SCHEMA, handle it manually
        if table_name.lower() == "sales":
            all_data = await self.get_all(table_name)
        else:
            all_data = await self.get_all(table_name)

        if not all_data:
            alias = ast.expressions[0].alias_or_name
            return [{_camelize_keys({alias: 0})[alias]: 0.0}]

        schema_def = TPCH_SCHEMA.get(table_name.lower(), {})
        decimal_cols = {
            col
            for col, type_str in zip(
                schema_def.get("columns", []), schema_def.get("types", [])
            )
            if "decimal" in type_str
        }
        if table_name.lower() == "sales":
            decimal_cols.add("amount")

        for row in all_data:
            for key, value in row.items():
                if isinstance(value, neo_time.Date):
                    row[key] = date(value.year, value.month, value.day)
                elif key in decimal_cols and isinstance(value, (float, int)):
                    row[key] = Decimal(str(value))

        spark_schema = self._get_spark_schema(table_name)
        df = self.spark.createDataFrame(all_data, schema=spark_schema)

        agg_expressions = []
        for expr in ast.expressions:
            alias = expr.alias_or_name
            core_expr = expr.this if isinstance(expr, exp.Alias) else expr

            if isinstance(core_expr, exp.AggFunc):
                spark_col_expr = self._translate_expression_to_spark(
                    core_expr.this
                )  # noqa:F501

                if isinstance(core_expr, exp.Count):
                    agg_expressions.append(
                        F.count(spark_col_expr).alias(alias)
                    )  # noqa:F501
                elif isinstance(core_expr, exp.Sum):
                    agg_expressions.append(F.sum(spark_col_expr).alias(alias))
                elif isinstance(core_expr, exp.Avg):
                    agg_expressions.append(F.avg(spark_col_expr).alias(alias))
            else:
                msg = f"Unsupported expression in aggregate: {expr.sql()}"
                raise NotImplementedError(msg)

        result_df = df.agg(*agg_expressions)
        results = [row.asDict() for row in result_df.collect()]
        return [_camelize_keys(row) for row in results]

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> int:
        """
        Performs a high-performance bulk insert using batched UNWIND ops.
        Returns the number of records inserted.
        """
        driver = self._get_driver()
        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            # Manually define schema for 'sales' table for the test
            if table_name.lower() == "sales":
                schema = {
                    "columns": ["sale_id", "amount", "sale_date"],
                    "types": ["str", "decimal", "date"],
                }
            else:
                msg = f"No schema definition found for table: {table_name}"
                raise ValueError(msg)

        cols = schema["columns"]
        label = table_name.capitalize()
        DynamicModel = get_pydantic_model(table_name, schema)

        async with driver.session() as s:
            await s.run(f"MATCH (n:{label}) DETACH DELETE n")

        props_str = ", ".join([f"`{c}`: row.`{c}`" for c in cols])
        cypher_query = f"""
        CALL {{
            UNWIND $rows AS row
            CREATE (n:{label} {{ {props_str} }})
        }} IN TRANSACTIONS OF 1000 ROWS
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
                        validated_data = DynamicModel(**row_dict)
                        model_dict = validated_data.model_dump()
                        for key, value in model_dict.items():
                            if isinstance(value, date):
                                model_dict[key] = neo_time.Date(
                                    value.year, value.month, value.day
                                )
                        batch.append(model_dict)
                    except ValidationError as e:
                        msg = "Skipping row due to validation "
                        msg += f"error: {line}. Error: {e}"
                        logging.warning(msg)
                        continue

                    if len(batch) >= batch_size:
                        async with driver.session() as s:
                            result = await s.run(cypher_query, rows=batch)
                            summary = await result.consume()
                            total_inserted += summary.counters.nodes_created
                        batch = []

                if batch:
                    async with driver.session() as s:
                        result = await s.run(cypher_query, rows=batch)
                        summary = await result.consume()
                        total_inserted += summary.counters.nodes_created
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Error during bulk insert for {table_name}: {e}")
            raise

        return total_inserted

    def _get_spark_schema(self, table_name: str) -> StructType:
        """Generates a Spark schema from the TPCH schema definition."""
        sch_def = TPCH_SCHEMA.get(table_name.lower())
        if not sch_def:
            if table_name.lower() == "sales":
                return StructType(
                    [
                        StructField("sale_id", StringType(), True),
                        StructField("amount", DecimalType(10, 2), True),
                        StructField("sale_date", DateType(), True),
                    ]
                )
            msg = f"No schema definition found for table: {table_name}"
            raise ValueError(msg)

        fields = []
        for c_name, c_type in zip(sch_def["columns"], sch_def["types"]):
            if c_type == "date":
                fields.append(StructField(c_name, DateType(), True))
            elif "decimal" in c_type:
                precision, scale = 38, 10  # Default
                if "(" in c_type and ")" in c_type:
                    try:
                        prts = c_type.split("(")[1].replace(")", "").split(",")
                        if len(prts) == 2:
                            precision, scale = map(int, prts)
                    except (ValueError, IndexError):
                        pass
                fields.append(
                    StructField(c_name, DecimalType(precision, scale), True)
                )  # noqa:F501
            else:
                fields.append(StructField(c_name, StringType(), True))
        return StructType(fields)

    def _translate_expression_to_spark(self, expr):
        """
        Recursively translates a sqlglot expression into a PySpark column
        expression.
        """
        if isinstance(expr, exp.Star):
            return F.lit(1)
        if isinstance(expr, exp.Column):
            return F.col(expr.sql())
        if isinstance(expr, exp.Literal):
            val = expr.this
            return F.lit(Decimal(val) if not expr.is_string else val)
        if isinstance(expr, exp.Mul):
            left = self._translate_expression_to_spark(expr.left)
            right = self._translate_expression_to_spark(expr.right)
            return left * right
        if isinstance(expr, exp.Sub):
            left = self._translate_expression_to_spark(expr.left)
            right = self._translate_expression_to_spark(expr.right)
            return left - right
        if isinstance(expr, exp.Add):
            left = self._translate_expression_to_spark(expr.left)
            right = self._translate_expression_to_spark(expr.right)
            return left + right
        if isinstance(expr, exp.LTE):
            left = self._translate_expression_to_spark(expr.left)
            right = self._translate_expression_to_spark(expr.right)
            return left <= right
        if isinstance(expr, exp.Paren):
            return self._translate_expression_to_spark(expr.this)

        if (
            isinstance(expr, exp.Cast)
            and expr.to.this == exp.DataType.Type.DATE  # noqa:F501
        ):  # noqa:F501
            return F.to_date(self._translate_expression_to_spark(expr.this))

        raise NotImplementedError(f"Unsupported expression type: {type(expr)}")
