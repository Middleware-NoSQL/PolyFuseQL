import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
import redis.asyncio as aioredis
from sqlglot import exp
import csv
from pydantic import ValidationError
from decimal import Decimal, InvalidOperation

# PySpark Integration
try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        StructType,
        StructField,
        StringType,
        DecimalType,
        DateType,
        IntegerType,
    )
    from pyspark.errors import PySparkException

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


class RedisConnector(Connector):
    """Connector for Redis with persistent connection handling
    and PySpark for complex queries."""

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options or {})
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "tpch")
        self._client: Optional[aioredis.Redis] = None
        self.spark: Optional["SparkSession"] = None
        self._dependencies_zip: Optional[str] = None

    def _prepare_dependencies(self) -> None:
        """
        Packages the project's virtual environment dependencies into a zip
        file for distribution to Spark workers. This is crucial for ensuring
        that libraries like 'redis' are available on all nodes.
        """
        project_root = Path(__file__).parent.parent.parent
        zip_path = project_root / "dependencies.zip"
        self._dependencies_zip = str(zip_path)

        if zip_path.exists():
            logging.info(f"Dependency file already exists: {zip_path}")
            return

        logging.info(f"Creating dependencies zip file at: {zip_path}")
        try:
            venv_path = Path(sys.prefix)
            site_packages = next(venv_path.glob("**/site-packages"))

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in site_packages.rglob("*"):
                    arcname = file.relative_to(site_packages)
                    zf.write(file, arcname)
            logging.info("Successfully created dependencies.zip.")
        except Exception as e:
            logging.error(f"Failed to create dependencies zip file: {e}")
            self._dependencies_zip = None

    def _init_spark(self) -> Optional["SparkSession"]:
        """
        Initializes the SparkSession, ensuring it's configured with the
        necessary dependencies for distributed execution. It uses a robust
        method of adding dependencies to an existing session if one is found.
        """
        if not SPARK_AVAILABLE:
            logging.warning("PySpark not found. Complex queries will be slow.")
            return None
        try:
            spark_master_url = env("SPARK_MASTER_URL", "local[*]")

            builder = (
                SparkSession.builder.appName("PolyFuseQL-Connector")
                .master(spark_master_url)
                .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
            )

            if "local" not in spark_master_url:
                builder = builder.config("spark.driver.memory", "4g")
                builder = builder.config("spark.executor.memory", "3g")
            else:
                builder = builder.config("spark.driver.memory", "4g")

            # getOrCreate safely handles existing sessions.
            spark_session = builder.getOrCreate()
            logging.info("Spark session obtained.")

            # If running on a cluster, programmatically add dependencies.
            # This is more reliable than configuring at build time and works
            # even if another connector created the session.
            if "local" not in spark_master_url:
                self._prepare_dependencies()
                if self._dependencies_zip:
                    # addPyFile distributes the file and adds it to the
                    # PYTHONPATH on all worker nodes.
                    spark_session.sparkContext.addPyFile(
                        self._dependencies_zip
                    )  # noqa:F501
                    msg = "Added dependency file to Python"
                    msg += f" path on all workers: {self._dependencies_zip}"
                    logging.info(msg)

            return spark_session

        except PySparkException as e:
            logging.error(f"Failed to initialize SparkSession: {e}")
            return None

    async def connect(self) -> None:
        if not self._client:
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                decode_responses=True,
                password=self._password,
            )
            logging.info("Redis client initialized.")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            logging.info("Redis connection closed.")
        if self.spark:
            self.spark.stop()
            self.spark = None
            logging.info("SparkSession stopped.")
        if self._dependencies_zip and os.path.exists(self._dependencies_zip):
            try:
                os.remove(self._dependencies_zip)
                msg = "Removed temporary dependencies file: "
                msg += f"{self._dependencies_zip}"
                logging.info(msg)
            except OSError as e:
                logging.warning(f"Error removing dependencies file: {e}")

    def _get_client(self) -> aioredis.Redis:
        if not self._client:
            raise ConnectionError(
                "RedisConnector is not connected. Call connect() first."
            )
        return self._client

    async def ping(self) -> bool:
        r = self._get_client()
        return await r.ping()

    async def count(self, entity: str) -> int:
        r = self._get_client()
        prfx = f"{entity.capitalize()}:*"
        total = 0
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=prfx, count=1000)
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa:F501
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        raw_data = await r.hgetall(key)
        if not raw_data:
            return {}

        schema = TPCH_SCHEMA.get(entity.lower())
        if not schema:
            return raw_data

        DynamicModel = get_pydantic_model(entity, schema)
        try:
            validated_model = DynamicModel(**raw_data)
            return validated_model.model_dump()
        except ValidationError:
            return raw_data

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        r = self._get_client()
        pk_col = self._options.get("pk", "id")
        pk_val = payload.get(pk_col)
        if not pk_val:
            pk_val = next(iter(payload.values()))

        key = f"{entity.capitalize()}:{pk_val}"
        str_payload = {k: str(v) for k, v in payload.items()}
        await r.hset(key, mapping=str_payload)
        return {"status": "inserted", "key": key}

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        if not await r.exists(key):
            return 0
        str_payload = {k: str(v) for k, v in payload.items()}
        await r.hset(key, mapping=str_payload)
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        return await r.delete(key)

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        r = self._get_client()
        keys = await r.keys(f"{entity.capitalize()}:*")
        if not keys:
            return []
        pipe = r.pipeline()
        for key in keys:
            pipe.hgetall(key)
        results = await pipe.execute()
        return [dict(res) for res in results if res]

    async def query(
        self, sql: str, params: tuple = None
    ) -> List[dict[str, Any]]:  # noqa:F501
        msg = "RedisConnector does not support raw SQL queries."
        raise NotImplementedError(msg)

    def _get_spark_schema(self, table_name: str) -> Optional["StructType"]:
        schema_def = TPCH_SCHEMA.get(table_name.lower())
        if not schema_def:
            return None
        type_mapping = {
            "int": IntegerType(),
            "str": StringType(),
            "date": DateType(),
            "decimal": DecimalType(18, 4),
        }
        fields = [
            StructField(
                col_name, type_mapping.get(col_type, StringType()), True
            )  # noqa:F501
            for col_name, col_type in zip(
                schema_def["columns"], schema_def["types"]
            )  # noqa:F501
        ]
        return StructType(fields)

    def _translate_expression_to_spark(self, expression: exp.Expression):
        """Recursively translates a sqlglot expression to
        a PySpark Column expression."""
        if isinstance(expression, exp.Star):
            return F.lit(1)
        if isinstance(expression, exp.Column):
            return F.col(expression.this.name)
        if isinstance(expression, exp.Literal):
            try:
                return F.lit(Decimal(expression.this))
            except InvalidOperation:
                return F.lit(expression.this)
        if isinstance(expression, exp.Paren):
            return self._translate_expression_to_spark(expression.this)

        if isinstance(expression, exp.Binary):
            left = self._translate_expression_to_spark(expression.left)
            right = self._translate_expression_to_spark(expression.right)
            if isinstance(expression, exp.Mul):
                return left * right
            if isinstance(expression, exp.Sub):
                return left - right
            if isinstance(expression, exp.Add):
                return left + right
            if isinstance(expression, exp.LTE):
                return left <= right

        if (
            isinstance(expression, exp.Cast)
            and expression.to.this == exp.DataType.Type.DATE
        ):
            return F.to_date(F.lit(expression.this.this))
        msg = "Unsupported SQL expression for "
        msg += f"Spark translation: {type(expression)}"
        raise NotImplementedError(msg)

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        if not self.spark:
            raise NotImplementedError("PySpark is not available for JOINs.")
        msg = "PySpark JOIN logic is not fully implemented yet."
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        if self.spark is None:
            self.spark = self._init_spark()
        if not self.spark:
            raise RuntimeError("PySpark is required for GROUP BY operations.")

        table_name = ast.find(exp.Table).name

        logging.info(f"Fetching keys for table '{table_name}' from Redis.")
        r = self._get_client()
        keys = await r.keys(f"{table_name.capitalize()}:*")
        if not keys:
            logging.warning(f"No keys found for table '{table_name}'.")
            return []
        logging.info(f"Found {len(keys)} keys. Distributing to Spark workers.")

        num_slices = self.spark.sparkContext.defaultParallelism * 4
        keys_rdd = self.spark.sparkContext.parallelize(
            keys, numSlices=num_slices
        )  # noqa:F501

        redis_host = self._host
        redis_port = self._port
        redis_password = self._password

        def fetch_redis_data_partitions(iterator):
            import redis

            partition_keys = list(iterator)
            if not partition_keys:
                return iter([])

            r_sync = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                decode_responses=True,
            )
            pipe = r_sync.pipeline(transaction=False)

            for key in partition_keys:
                pipe.hgetall(key)

            return iter(pipe.execute())

        logging.info("Spark workers are now fetching data from Redis.")
        data_rdd = keys_rdd.mapPartitions(fetch_redis_data_partitions)

        if data_rdd.isEmpty():
            msg = "No data returned from Redis after parallel fetch."
            logging.warning(msg)
            return []

        df = data_rdd.toDF()

        target_spark_schema = self._get_spark_schema(table_name)
        if not target_spark_schema:
            raise ValueError(f"No Spark schema defined for table {table_name}")

        for field in target_spark_schema.fields:
            col_name = field.name
            if col_name in df.columns:
                df = df.withColumn(
                    col_name, F.col(col_name).cast(field.dataType)
                )  # noqa:F501

        logging.info("Successfully created and typed Spark DataFrame.")

        where_clause = ast.args.get("where")
        if where_clause:
            filter_condition = self._translate_expression_to_spark(
                where_clause.this
            )  # noqa:F501
            df = df.filter(filter_condition)
            logging.info("Applied WHERE clause.")

        group_by_cols = [
            col.this.name for col in ast.args.get("group").expressions
        ]  # noqa:F501
        grouped_df = df.groupBy(*group_by_cols)
        logging.info(f"Applied GROUP BY on: {group_by_cols}")

        agg_expressions = []
        final_select_cols = [e.alias_or_name for e in ast.expressions]

        for expression in ast.expressions:
            if isinstance(expression, exp.Alias) and isinstance(
                expression.this, exp.AggFunc
            ):
                agg_func = expression.this
                alias = expression.alias_or_name
                inner_expr = self._translate_expression_to_spark(agg_func.this)

                high_precision_decimal = DecimalType(38, 6)

                if isinstance(agg_func, exp.Sum):
                    agg_expr = (
                        F.sum(inner_expr)
                        .cast(high_precision_decimal)
                        .alias(alias)  # noqa:F501
                    )
                elif isinstance(agg_func, exp.Avg):
                    agg_expr = (
                        F.avg(inner_expr)
                        .cast(high_precision_decimal)
                        .alias(alias)  # noqa:F501
                    )
                elif isinstance(agg_func, exp.Count):
                    agg_expr = F.count(inner_expr).alias(alias)
                else:
                    raise NotImplementedError(
                        f"Unsupported aggregate function: {type(agg_func)}"
                    )
                agg_expressions.append(agg_expr)

        agg_df = grouped_df.agg(*agg_expressions)
        logging.info("Applied aggregations.")

        order_by_clause = ast.args.get("order")
        if order_by_clause:
            order_cols = [col.this.name for col in order_by_clause.expressions]
            agg_df = agg_df.orderBy(*order_cols)
            logging.info(f"Applied ORDER BY on: {order_cols}")

        final_df = agg_df.select(*final_select_cols)

        logging.info("Spark job starting collection...")
        results = [row.asDict() for row in final_df.collect()]
        logging.info(f"Spark job finished. Collected {len(results)} rows.")

        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        table_name = ast.find(exp.Table).name
        all_data = await self.get_all(table_name)
        result_row = {}
        if not all_data:
            return [{}]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa:F501
                agg_func = expr.this
                alias = expr.alias_or_name

                if isinstance(agg_func, exp.Count):
                    result_row[alias] = len(all_data)
                    continue

                values = [
                    self._evaluate_expression(agg_func.this, row)
                    for row in all_data  # noqa:F501
                ]

                if isinstance(agg_func, exp.Sum):
                    result_row[alias] = sum(values)
                elif isinstance(agg_func, exp.Avg):
                    result_row[alias] = (
                        sum(values) / Decimal(len(values))
                        if values
                        else Decimal("0.0")  # noqa:F501
                    )

        return [_camelize_keys(result_row)]

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        r = self._get_client()
        if table_name.lower() in ["lineitem", "sales"]:
            await r.flushdb()
        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            raise ValueError(f"No schema for table: {table_name}")

        columns, pk_info = schema["columns"], schema["pk"]
        DynamicModel = get_pydantic_model(table_name, schema)
        inserted_count, batch = 0, []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")
                for row in reader:
                    if not row or len(row) < len(columns):
                        continue
                    try:
                        row_dict = dict(zip(columns, row[: len(columns)]))
                        validated_data = DynamicModel(**row_dict)
                        batch.append(validated_data.model_dump())
                        inserted_count += 1
                    except ValidationError as e:
                        msg = f"Skipping malformed row: {row}. "
                        msg += f"Error: {e}"
                        logging.warning(msg)
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            return 0

        async with r.pipeline(transaction=False) as pipe:
            for payload in batch:
                pk_val = (
                    ":".join([str(payload[k]) for k in pk_info])
                    if isinstance(pk_info, list)
                    else payload[pk_info]
                )
                key = f"{table_name.capitalize()}:{pk_val}"
                str_payload = {k: str(v) for k, v in payload.items()}
                await pipe.hset(key, mapping=str_payload)
            await pipe.execute()
        return inserted_count

    def _evaluate_expression(self, expression, row_data):
        if isinstance(expression, exp.Column):
            val = row_data.get(expression.sql())
            try:
                return Decimal(val) if val is not None else Decimal("0.0")
            except (InvalidOperation, TypeError):
                return Decimal("0.0")
        if isinstance(expression, exp.Literal):
            return Decimal(expression.this)
        if isinstance(expression, exp.Mul):
            return self._evaluate_expression(
                expression.left, row_data
            ) * self._evaluate_expression(expression.right, row_data)
        if isinstance(expression, exp.Sub):
            return self._evaluate_expression(
                expression.left, row_data
            ) - self._evaluate_expression(expression.right, row_data)
        if isinstance(expression, exp.Add):
            return self._evaluate_expression(
                expression.left, row_data
            ) + self._evaluate_expression(expression.right, row_data)
        if isinstance(expression, exp.Paren):
            return self._evaluate_expression(expression.this, row_data)
        raise NotImplementedError(
            f"Unsupported expression: {type(expression)}"
        )  # noqa:F501
