# ruff: noqa E501

import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
import redis
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
        # FIX: Defer SparkSession creation until it's actually needed
        # to avoid conflicts with other connectors during initialization.
        self.spark: Optional["SparkSession"] = None

    def _init_spark(self) -> Optional["SparkSession"]:
        """Initializes and returns a local SparkSession
        if PySpark is available."""
        if not SPARK_AVAILABLE:
            msg = "PySpark not found. Complex queries like JOIN and "
            msg += "GROUP BY will be slow and memory-intensive."
            logging.warning(msg)
            return None
        try:
            # --- Spark Session Configuration ---
            # To use workers, you must run a Spark Standalone cluster.
            # 1. Start Master: ./sbin/start-master.sh
            # 2. Start Worker: ./sbin/start-worker.sh spark://<your-ip>:7077
            # The master URL will be printed when you start the master.
            spark_master_url = "local[*]"  # Default to local mode
            # spark_master_url = "spark://cuscungo:7077"
            # spark_master_url = "spark://<your-ip>:7077"
            # Example for standalone cluster

            builder = (
                SparkSession.builder.appName("RedisConnector")
                .master(spark_master_url)
                .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
            )

            if "local" not in spark_master_url:
                # --- Configuration for a Normal PC ---
                # Use a portion of resources to keep the system responsive.
                builder = builder.config("spark.driver.memory", "2g")
                builder = builder.config("spark.executor.cores", "8")
                builder = builder.config("spark.executor.memory", "4g")

                # --- Configuration for a High-Memory Server ---
                # Uncomment below to configure for
                # a server with more resources.
                # builder = builder.config("spark.driver.memory", "8g")
                # builder = builder.config("spark.executor.instances", "6")
                # builder = builder.config("spark.executor.cores", "5")
                # builder = builder.config("spark.executor.memory", "15g")
                # builder = builder
                #   .config("spark.sql.shuffle.partitions", "200")
            else:
                # Default memory for local mode
                builder = builder.config("spark.driver.memory", "4g")

            # getOrCreate() ensures that we use the existing SparkSession
            # if one has already been created by another connector.
            spark_session = builder.getOrCreate()
            logging.info("Spark session initialized.")
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
            # Note: In a multi-connector setup, stopping the session here
            # might affect other connectors. Ideally, the lifecycle
            # should be managed by the main client application.
            self.spark.stop()
            self.spark = None
            logging.info("SparkSession stopped.")

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
        raw_data = await r.hgetall(key)  # Assuming HASH for simplicity
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
            return F.lit(1)  # For use in COUNT(*) -> F.count(F.lit(1))
        if isinstance(expression, exp.Column):
            return F.col(expression.this.name)
        if isinstance(expression, exp.Literal):
            # Ensure literals used in calculations are treated as Decimals
            try:
                return F.lit(Decimal(expression.this))
            except InvalidOperation:
                return F.lit(expression.this)
        if isinstance(expression, exp.Paren):
            return self._translate_expression_to_spark(expression.this)

        # Handle binary operations
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

        # Handle date casting e.g., date '1998-09-02'
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
        """
        Performs a GROUP BY operation using PySpark for efficiency.
        This implementation is optimized to avoid pulling all data into the
        driver's memory. It fetches keys from Redis and then uses Spark
        workers to fetch the data in parallel, distributing the load.
        """
        if self.spark is None:
            self.spark = self._init_spark()
        if not self.spark:
            raise RuntimeError("PySpark is required for GROUP BY operations.")

        table_name = ast.find(exp.Table).name

        # OPTIMIZATION: Instead of the driver pulling all data via get_all(),
        # fetch only the keys and let Spark
        # workers fetch hash data in parallel.
        logging.info(f"Fetching keys for table '{table_name}' from Redis.")
        r = self._get_client()
        keys = await r.keys(f"{table_name.capitalize()}:*")
        if not keys:
            logging.warning(f"No keys found for table '{table_name}'.")
            return []
        logging.info(f"Found {len(keys)} keys. Distributing to Spark workers.")

        # 1. Distribute keys into a Spark RDD for parallel processing.
        # Increasing slices can improve parallelism for I/O bound tasks.
        num_slices = self.spark.sparkContext.defaultParallelism * 4
        keys_rdd = self.spark.sparkContext.parallelize(
            keys, numSlices=num_slices
        )  # noqa:F501

        # 2. Define the function for workers to fetch data from Redis.
        # This function runs on each partition of the RDD.
        redis_host = self._host
        redis_port = self._port
        redis_password = self._password

        def fetch_redis_data_partitions(iterator):
            """
            Executed on each Spark worker to fetch a partition of data.
            Uses a standard synchronous Redis client.
            """
            partition_keys = list(iterator)
            if not partition_keys:
                return iter([])

            # Each worker gets its own Redis client.
            r_sync = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                decode_responses=True,
            )
            pipe = r_sync.pipeline(transaction=False)

            for key in partition_keys:
                pipe.hgetall(key)

            # pipe.execute() returns a list of dictionaries (str -> str)
            return iter(pipe.execute())

        # 3. Execute the data fetching in parallel across the Spark cluster.
        logging.info("Spark workers are now fetching data from Redis.")
        data_rdd = keys_rdd.mapPartitions(fetch_redis_data_partitions)

        # Check for empty results early to avoid creating an empty DataFrame.
        if data_rdd.isEmpty():
            msg = "No data returned from Redis after parallel fetch."
            logging.warning(msg)
            return []

        # 4. Create a DataFrame. Spark will infer a schema of all string types.
        df = data_rdd.toDF()

        # 5. Cast columns to their correct,
        # final types using the defined schema.
        # This is more efficient than pre-processing in Python on the driver.
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

        # 6. Apply WHERE clause
        where_clause = ast.args.get("where")
        if where_clause:
            filter_condition = self._translate_expression_to_spark(
                where_clause.this
            )  # noqa:F501
            df = df.filter(filter_condition)
            logging.info("Applied WHERE clause.")

        # 7. Apply GROUP BY
        group_by_cols = [
            col.this.name for col in ast.args.get("group").expressions
        ]  # noqa:F501
        grouped_df = df.groupBy(*group_by_cols)
        logging.info(f"Applied GROUP BY on: {group_by_cols}")

        # 8. Build aggregation expressions
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

        # 9. Apply ORDER BY
        order_by_clause = ast.args.get("order")
        if order_by_clause:
            order_cols = [
                col.this.this.name for col in order_by_clause.expressions
            ]  # noqa:F501
            agg_df = agg_df.orderBy(*order_cols)
            logging.info(f"Applied ORDER BY on: {order_cols}")

        # 10. Ensure final column order matches the original query
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
                        logging.warning(
                            f"Skipping malformed row: {row}. Error: {e}"
                        )  # noqa:F501
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
