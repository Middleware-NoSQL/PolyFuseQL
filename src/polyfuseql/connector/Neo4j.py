# ruff: noqa E501

import csv
import logging
import sys
from datetime import date
from decimal import Decimal
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
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        DateType,
        DecimalType,
        DoubleType,
        StringType,
        StructField,
        StructType,
    )
except ImportError:
    pass


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

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        msg = "JOIN is not fully implemented for Neo4j connector."
        raise NotImplementedError(msg)

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    def _translate_where_to_cypher_literal(
        self, where_expr: exp.Expression
    ) -> str:  # noqa:F501
        if isinstance(where_expr, exp.LTE):
            col_name = where_expr.left.sql()
            is_cast = isinstance(where_expr.right, exp.Cast)
            is_date = where_expr.right.to.this == exp.DataType.Type.DATE
            if is_cast and is_date:
                date_str = where_expr.right.this.this
                return f"WHERE n.`{col_name}` <= date('{date_str}')"
        msg = f"Unsupported WHERE for Cypher translation: {type(where_expr)}"
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for GROUP BY operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        table_name = ast.find(exp.Table).name
        label = table_name.capitalize()
        spark_schema = self._get_spark_schema(table_name)

        read_schema_fields = []
        return_expressions = []

        for field in spark_schema.fields:
            if isinstance(field.dataType, (DecimalType, DoubleType)):
                read_schema_fields.append(
                    StructField(field.name, DoubleType(), True)
                )  # noqa:F501
                return_expressions.append(
                    f"toFloat(n.{field.name}) AS {field.name}"
                )  # noqa:F501
            else:
                read_schema_fields.append(field)
                return_expressions.append(f"n.{field.name} AS {field.name}")
        read_schema = StructType(read_schema_fields)

        cypher_query = f"MATCH (n:{label}) "
        if ast.args.get("where"):
            where_this = ast.args["where"].this
            cypher_where_clause = self._translate_where_to_cypher_literal(
                where_this
            )  # noqa:F501
            cypher_query += cypher_where_clause
        cypher_query += f" RETURN {', '.join(return_expressions)}"

        logging.info(
            f"Using Spark connector with Cypher query: {cypher_query}"
        )  # noqa:F501

        df = (
            spark.read.format("org.neo4j.spark.DataSource")
            .option("url", self._uri)
            .option("authentication.type", "basic")
            .option("authentication.basic.username", self._auth[0])
            .option("authentication.basic.password", self._auth[1])
            .option("query", cypher_query)
            .schema(read_schema)
            .load()
        )

        for field in spark_schema.fields:
            if isinstance(field.dataType, DecimalType):
                df = df.withColumn(
                    field.name, F.col(field.name).cast(field.dataType)
                )  # noqa:F501

        if df.isEmpty():
            return []

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

        logging.info("Spark job starting collection...")
        results = [row.asDict() for row in result_df.collect()]
        logging.info("Spark job collection finished.")

        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for aggregate operations "
            msg += "but is not available."
            raise RuntimeError(msg)

        table_name = ast.find(exp.Table).name
        label = table_name.capitalize()
        spark_schema = self._get_spark_schema(table_name)

        read_schema_fields = []
        return_expressions = []
        for field in spark_schema.fields:
            if isinstance(field.dataType, (DecimalType, DoubleType)):
                read_schema_fields.append(
                    StructField(field.name, DoubleType(), True)
                )  # noqa:F501
                return_expressions.append(
                    f"toFloat(n.{field.name}) AS {field.name}"
                )  # noqa:F501
            else:
                read_schema_fields.append(field)
                return_expressions.append(f"n.{field.name} AS {field.name}")
        read_schema = StructType(read_schema_fields)
        msg = f"MATCH (n:{label}) RETURN {', '.join(return_expressions)}"
        cypher_query = msg

        df = (
            spark.read.format("org.neo4j.spark.DataSource")
            .option("url", self._uri)
            .option("authentication.type", "basic")
            .option("authentication.basic.username", self._auth[0])
            .option("authentication.basic.password", self._auth[1])
            .option("query", cypher_query)
            .schema(read_schema)
            .load()
        )

        for field in spark_schema.fields:
            if isinstance(field.dataType, DecimalType):
                df = df.withColumn(
                    field.name, F.col(field.name).cast(field.dataType)
                )  # noqa:F501

        if df.isEmpty():
            alias = ast.expressions[0].alias_or_name
            return [{_camelize_keys({alias: 0})[alias]: Decimal(0.0)}]

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
                raise NotImplementedError(
                    f"Unsupported expression in aggregate: {expr.sql()}"
                )

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

    def _translate_expression_to_spark(self, expr):
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
            and expr.to.this == exp.DataType.Type.DATE  # noqa: E501
        ):  # noqa:F501
            return F.to_date(self._translate_expression_to_spark(expr.this))
        raise NotImplementedError(f"Unsupported expression type: {type(expr)}")
