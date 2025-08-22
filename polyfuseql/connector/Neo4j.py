import logging
from datetime import date
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
from neo4j import AsyncGraphDatabase as AGD, AsyncDriver, time as neo_time
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from sqlglot import exp
import csv
from pydantic import ValidationError
from decimal import Decimal
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    DateType,
    DecimalType,
)


class Neo4jConnector(Connector):
    """Connector for Neo4j with PySpark for efficient aggregations."""

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        driver = self._get_driver()
        cypher_query = f"MATCH (n:{entity.capitalize()}) "
        cypher_query += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher_query)
            return [rec["p"] async for rec in result]

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        host = env("NEO4J_HOST", "localhost")
        port = env("NEO4J_PORT", "7687")
        user = env("NEO4J_USER", "neo4j")
        password = env("NEO4J_PASSWORD", "password")
        self._uri = f"bolt://{host}:{port}"
        self._auth = (user, password)
        self._driver: Optional[AsyncDriver] = None

        # --- Spark Session Configuration ---
        # To use workers, you must run a Spark Standalone cluster.
        # 1. Start Master: ./sbin/start-master.sh
        # 2. Start Worker: ./sbin/start-worker.sh spark://<your-ip>:7077
        # The master URL will be printed when you start the master.
        spark_master_url = "local[*]"  # Default to local mode
        # spark_master_url = "spark://<your-ip>:7077"
        # Example for standalone cluster

        builder = SparkSession.builder.appName("Neo4jConnector").master(
            spark_master_url
        )

        if "local" not in spark_master_url:
            # --- Configuration for a Normal PC ---
            # Use a portion of resources to keep the system responsive.
            builder = builder.config("spark.driver.memory", "2g")
            builder = builder.config("spark.executor.cores", "4")
            builder = builder.config("spark.executor.memory", "8g")

            # --- Configuration for a High-Memory Server ---
            # Uncomment below to configure for a server with more resources.
            # builder = builder.config("spark.driver.memory", "8g")
            # builder = builder.config("spark.executor.instances", "6")
            # builder = builder.config("spark.executor.cores", "5")
            # builder = builder.config("spark.executor.memory", "15g")
            # builder = builder.config("spark.sql.shuffle.partitions", "200")

        self.spark = builder.getOrCreate()
        logging.info("Spark session initialized.")

    async def connect(self) -> None:
        if not self._driver:
            # The modern neo4j driver automatically
            # detects the running event loop.
            # Adding a connection timeout to prevent
            # hangs on long-running queries.
            self._driver = AGD.driver(
                self._uri, auth=self._auth, connection_timeout=30.0
            )
            logging.info("Neo4j driver initialized.")
            await self.ping()

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logging.info("Neo4j driver closed.")
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

    async def count(self, label: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{label.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    async def get(self, lbl: str, pk_col: str, pk_val: Any) -> Dict[str, Any]:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher_match = f"MATCH (n:{lbl.capitalize()}) "
            cypher_where = f"WHERE n.`{pk_col}` "
            cypher = (
                cypher_match
                + cypher_where
                + "= $pk_val RETURN properties(n) AS p LIMIT 1"
            )
            result = await s.run(cypher, pk_val=pk_val)
            rec = await result.single()
            return rec["p"] if rec and rec["p"] else {}

    async def insert(self, label: str, payload: Dict[str, Any]) -> Any:
        driver = self._get_driver()
        props = ", ".join(f"`{k}`: ${k}" for k in payload.keys())

        cypher = f"CREATE (n:{label.capitalize()} {{ {props} }}) "
        cypher += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher, **payload)
            rec = await result.single()
            return rec["p"] if rec else {}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    async def delete(self, label: str, pk_col: str, pk_val: Any) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = (
                f"MATCH (n:{label.capitalize()} {{{pk_col}: $pk_val}}) "
                "DETACH DELETE n"
            )
            summary = await s.run(cypher, pk_val=pk_val)
            return 1 if summary else 0

    async def update(
        self, label: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = f"MATCH (n:{label} {{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            summary = await s.run(cypher, pk_val=pk_val, payload=payload)
            return 1 if summary else 0

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Manually translates a SQL JOIN AST to a Cypher query."""
        driver = self._get_driver()

        left_table_expr = ast.args.get("from").this
        join_expr = ast.args.get("joins")[0]
        right_table_expr = join_expr.this
        on_condition = join_expr.args.get("on")

        left_table_name = left_table_expr.this.name.capitalize()
        left_alias = left_table_expr.alias_or_name
        right_table_name = right_table_expr.this.name.capitalize()
        right_alias = right_table_expr.alias_or_name

        match_clause = (
            f"MATCH ({left_alias}:{left_table_name}), "
            f"({right_alias}:{right_table_name})"
        )
        on_left = f"{on_condition.this.table}.{on_condition.this.this.name}"
        on_right = f"{on_condition.expression.table}."
        on_right += f"{on_condition.expression.this.name}"
        where_clauses = [f"{on_left} = {on_right}"]

        params = {}
        if ast.args.get("where"):
            where_expr = ast.args["where"].this
            where_col = f"{where_expr.this.table}.{where_expr.this.this.name}"
            where_clauses.append(f"{where_col} = $where_val")

            lit_expr = where_expr.expression
            if lit_expr.is_string:
                params["where_val"] = lit_expr.this
            else:
                try:
                    params["where_val"] = int(lit_expr.this)
                except ValueError:
                    params["where_val"] = float(lit_expr.this)

        where_clause_str = " WHERE " + " AND ".join(where_clauses)

        return_expressions = []
        for col_expr in ast.expressions:
            col_name = col_expr.this.name
            table_alias = col_expr.table
            return_alias = f"`{col_name}`"
            exp_str = f"{table_alias}.{col_name} AS {return_alias}"
            return_expressions.append(exp_str)

        return_clause_str = "RETURN " + ", ".join(return_expressions)
        cypher_query = f"{match_clause}{where_clause_str} {return_clause_str}"

        async with driver.session() as s:
            result = await s.run(cypher_query, **params)
            return [dict(record) async for record in result]

    def _get_spark_schema(self, table_name: str) -> StructType:
        """Generates a Spark schema from the TPCH schema definition."""
        sch_def = TPCH_SCHEMA.get(table_name.lower())
        if not sch_def:
            if table_name.lower() == "sales":
                return StructType(
                    [
                        StructField("sale_id", StringType(), True),
                        StructField("amount", DecimalType(38, 10), True),
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
                if "(" in c_type and ")" in c_type:
                    try:
                        prts = c_type.split("(")[1].replace(")", "").split(",")
                        if len(prts) == 2:
                            precision, scale = map(int, prts)
                            fields.append(
                                StructField(
                                    c_name, DecimalType(precision, scale), True
                                )  # noqa:F501
                            )
                        else:
                            fields.append(
                                StructField(c_name, DecimalType(38, 10), True)
                            )
                    except (ValueError, IndexError):
                        fields.append(
                            StructField(c_name, DecimalType(38, 10), True)
                        )  # noqa:F501
                else:
                    fields.append(
                        StructField(c_name, DecimalType(38, 10), True)
                    )  # noqa:F501
            else:
                fields.append(StructField(c_name, StringType(), True))
        return StructType(fields)

    def _translate_expression_to_spark(self, expr):
        """Recursively translates a sqlglot expression into a
        PySpark column expression."""
        if isinstance(expr, exp.Column):
            return F.col(expr.sql())
        if isinstance(expr, exp.Literal):
            if expr.is_string:
                return F.lit(expr.this)
            return F.lit(Decimal(expr.this))
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
        if isinstance(expr, exp.Star):
            return F.lit(1)

        raise NotImplementedError(f"Unsupported expression type: {type(expr)}")

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Performs a GROUP BY operation using the PySpark DataFrame API."""
        table_name = ast.find(exp.Table).name
        all_data = await self.get_all(table_name)

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

        if ast.args.get("where"):
            where_condition = self._translate_expression_to_spark(
                ast.args["where"].this
            )
            df = df.filter(where_condition)

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

                if not isinstance(agg_func.this, (exp.Column, exp.Star)):
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

        results = [row.asDict() for row in result_df.collect()]
        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Performs aggregation using PySpark."""
        table_name = ast.find(exp.Table).name
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
                raise NotImplementedError(
                    f"Unsupported expression in aggregate: {expr.sql()}"
                )

        result_df = df.agg(*agg_expressions)
        results = [row.asDict() for row in result_df.collect()]
        return [_camelize_keys(row) for row in results]

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> tuple[int, int]:
        """
        Performs a high-performance bulk insert using batched
        UNWIND operations.
        """
        driver = self._get_driver()
        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            if table_name.lower() == "sales":
                schema = {
                    "columns": ["sale_id", "amount", "sale_date"],
                    "types": ["string", "decimal", "date"],
                }
            else:
                msg = f"No schema definition found for table: {table_name}"
                raise ValueError(msg)

        cols = schema["columns"]
        label = table_name.capitalize()

        DynamicModel = get_pydantic_model(table_name, schema)

        async with driver.session() as s:
            await s.run(f"MATCH (n:{label}) DETACH DELETE n")

        props_str = ", ".join([f"{col}: row.{col}" for col in cols])
        cypher_query = f"""
        CALL {{
            UNWIND $rows AS row
            CREATE (n:{label} {{ {props_str} }})
        }} IN TRANSACTIONS OF 1000 ROWS
        """

        total_inserted = 0
        total_lines = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")
                batch = []
                for line in reader:
                    if not line:
                        continue
                    line = line[: len(cols)]
                    if len(line) < len(cols):
                        logging.warning(
                            f"Skipping malformed row in {file_path}: {line}"
                        )
                        continue
                    total_lines += 1

                    try:
                        row_dict = dict(zip(cols, line))
                        validated_data = DynamicModel(**row_dict)

                        model_dict = validated_data.model_dump()
                        for key, value in model_dict.items():
                            if isinstance(value, date):
                                model_dict[key] = neo_time.Date(
                                    value.year, value.month, value.day
                                )
                        batch.append(model_dict)
                    except ValidationError as e:
                        msg = "Skipping row due to validation"
                        msg += f" error: {line}. Error: {e}"

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

        return total_inserted, total_lines
