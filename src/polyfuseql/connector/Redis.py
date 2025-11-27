import csv
import json
import logging
import asyncio  # Import asyncio for thread bridging
import aiofiles  # Import aiofiles
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, AsyncGenerator

import redis.asyncio as aioredis
from pydantic import ValidationError
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings
from polyfuseql.connector.Connector import Connector
from polyfuseql.connector.SparkTranslator import SparkTranslator
from polyfuseql.utils.spark_manager import get_spark_session
from polyfuseql.utils.utils import get_pydantic_model, _camelize_keys

try:
    from pyspark.sql import functions as F, DataFrame
    from pyspark.sql.types import (
        StructType,
        StructField,
        StringType,
        DecimalType,
        DateType,
        IntegerType,
    )

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


class RedisConnector(Connector, SparkTranslator):
    """Connector for Redis with configurable data type strategies."""

    def __init__(
        self,
        catalogue: Optional[Catalogue] = None,
        options: Optional[Dict] = None,
    ) -> None:
        super().__init__(options=options, catalogue=catalogue)
        self._host = settings.redis.host
        self._port = settings.redis.port
        self._password = settings.redis.password
        self._client: Optional[aioredis.Redis] = None

    def set_data_type(self, data_type: dict) -> None:
        self._options = data_type

    def get_data_type(self) -> str:
        """Returns the current data type strategy for Redis operations."""
        return self._options.get("data_type", settings.redis.data_type)

    async def connect(self) -> None:
        if not self._client:
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                password=self._password,
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

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
        # Correctly formatted prefix for scanning keys
        prfx = f"{entity.capitalize()}:*:{self.get_data_type()}"
        total = 0
        cursor = "0"
        while cursor != 0:
            cursor, keys = await r.scan(cursor=cursor, match=prfx, count=1000)
            total += len(keys)
        return total

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: E501
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        logging.info("Getting data from Redis: %s", key)
        data_type = self.get_data_type()
        logging.info("Data type: %s", data_type)
        raw_data = None
        if data_type == "string":
            raw_data_str = await r.get(key)
            if raw_data_str:
                try:
                    raw_data = json.loads(raw_data_str)
                except json.JSONDecodeError:
                    logging.warning(
                        f"Could not parse Redis string data: {raw_data_str}"
                    )
                    raw_data = None
        elif data_type == "json":
            raw_data = await r.json().get(key)
        else:  # 'hash' is the default
            raw_data = await r.hgetall(key)
        logging.info(f"Raw Data: {raw_data}")
        if not raw_data:
            return {}

        schema = self.catalogue.get_schema(entity)
        logging.info("Schema: %s", schema)
        if not schema:
            return _camelize_keys(raw_data)

        dynamic_model = get_pydantic_model(entity, schema)
        try:
            # Pydantic expects camelCase keys
            validated_model = dynamic_model(**raw_data)
            logging.info("Validated model: %s", validated_model.model_dump())
            return raw_data | validated_model.model_dump()
        except ValidationError:
            return _camelize_keys(raw_data)

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        r = self._get_client()
        schema = self.catalogue.get_schema(entity)
        if not schema:
            raise ValueError(f"No schema for table: {entity}")
        logging.info(f"insert-schema: {schema}")
        pk_col = schema["pk"]
        logging.info(f"insert-pk_col: {pk_col}")
        if isinstance(pk_col, list):
            pk_val = ":".join(str(payload.get(k)) for k in pk_col)
        else:
            pk_val = payload.get(pk_col)

        if not pk_val:
            raise ValueError("Primary key value not found in payload.")

        key = f"{entity.capitalize()}:{pk_val}"
        str_payload = {k: str(v) for k, v in payload.items()}
        data_type = self.get_data_type()

        logging.info(f"insert-key: {key}")
        logging.info(f"insert-str_payload: {str_payload}")
        logging.info(f"insert-data_type: {data_type}")
        if data_type == "string":
            await r.set(key, json.dumps(str_payload))
        elif data_type == "json":
            await r.json().set(key, "$", str_payload)
        else:  # 'hash' is the default
            await r.hset(key, mapping=str_payload)

        return {"status": "inserted", "key": key}

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        if self._options.get("include_data_type_in_pk", False):
            key += f":{self.get_data_type()}"
        if not await r.exists(key):
            return 0

        str_payload = {k: str(v) for k, v in payload.items()}
        data_type = self.get_data_type()

        if data_type in ["string", "json"]:
            if data_type == "string":
                current_data_str = await r.get(key)
                current_data = (
                    json.loads(current_data_str) if current_data_str else {}
                )  # noqa: E501
            else:  # json
                current_data = await r.json().get(key) or {}

            current_data.update(str_payload)
            if data_type == "string":
                await r.set(key, json.dumps(current_data))
            else:
                await r.json().set(key, "$", current_data)
        else:  # hash
            await r.hset(key, mapping=str_payload)
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        return await r.delete(key)

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        r = self._get_client()
        logging.info("Entity: %s", entity)

        keys = [
            key
            async for key in r.scan_iter(
                f"{entity.capitalize()}:*"
                + (
                    f":{self.get_data_type()}"
                    if self._options.get("include_data_type_in_pk", False)
                    else ""
                )
            )
        ]
        if not keys:
            logging.info("Not keys to get")
            return []

        # [FIX] Pipeline creation is synchronous
        pipe = r.pipeline()
        for key in keys:
            logging.info(f"get-key: {key}")
            if self.get_data_type() == "hash":
                # [FIX] Do not await pipeline queuing methods
                pipe.hgetall(key)
            else:
                # [FIX] Do not await pipeline queuing methods
                pipe.get(key)

        # [FIX] Only await the execution
        results = await pipe.execute()
        logging.info(f"Results: {results}")

        # Process results based on data type
        processed_results = []
        data_type = self.get_data_type()
        for res in results:
            if not res:
                continue
            if data_type == "hash":
                processed_results.append(dict(res))
            else:  # string or json
                try:
                    # [TECH DEBT FIX] Replaced unsafe literal_eval
                    # with json.loads
                    processed_results.append(json.loads(res))
                except (json.JSONDecodeError, TypeError):
                    logging.warning(f"Could not parse Redis result: {res}")
        return processed_results

    async def query(
        self, sql: str, params: tuple = None
    ) -> List[dict[str, Any]]:  # noqa: E501
        msg = "RedisConnector does not "
        msg += "support raw SQL queries."
        raise NotImplementedError(msg)

    def _get_spark_schema(self, table_name: str) -> Optional["StructType"]:
        schema_def = self.catalogue.get_schema(table_name)
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
            )  # noqa: E501
            for col_name, col_type in schema_def["columns"].items()
        ]
        return StructType(fields)

    # --- [SONARQUBE S3776 FIX & PYSPARK PICKLING FIX] ---
    # These methods are now STATIC to prevent capturing 'self'
    # (and the un-picklable Redis client)
    # in the RDD closure.

    @staticmethod
    def _process_redis_results(results: list, data_type: str):
        """
        (Worker-side) Processes raw results from a Redis pipeline.
        [Sonar Refactor] Helper for _fetch_redis_data_fallback
        to reduce cognitive complexity.
        """
        import json
        import logging

        if data_type not in ["string", "json"]:
            # This is the 'hash' case
            return iter(results)

        # This is the 'string' or 'json' case
        valid_results = []
        for res in results:
            if not res:
                continue
            try:
                valid_results.append(json.loads(res))
            except json.JSONDecodeError:
                logging.warning(f"Could not decode JSON:{res}")
        return iter(valid_results)

    @staticmethod
    def _fetch_redis_data_fallback(iterator, redis_config, data_type):
        """
        (Worker-side) Fetches data for string/json types.
        [Sonar Refactor] Delegated processing to _process_redis_results
        to reduce cognitive complexity.
        """
        import redis

        partition_keys = list(iterator)
        if not partition_keys:
            return iter([])

        # Establish a fresh, worker-local connection
        # Do NOT use the client from 'self' (which is why this is static)
        r_sync = redis.Redis(**redis_config, decode_responses=True)
        pipe = r_sync.pipeline(transaction=False)

        for key in partition_keys:
            if data_type == "hash":
                pipe.hgetall(key)
            else:  # string or json
                pipe.get(key)
        results = pipe.execute()
        r_sync.close()

        # [SONAR REFACTOR] Delegate processing to new helper method
        # Call via class name or local reference, NOT self
        return RedisConnector._process_redis_results(results, data_type)

    async def _load_table_hash_spark(
        self, table_name: str, spark_session, target_schema, data_type
    ) -> "DataFrame":
        """Loads a 'hash' table using the scalable spark-redis connector."""
        logging.info(
            f"Using scalable `spark-redis` connector for 'hash' table: {table_name}"  # noqa: E501
        )
        key_pattern = f"{table_name.capitalize()}:*"
        if self._options.get("include_data_type_in_pk", False):
            key_pattern += f":{data_type}"

        redis_config = {
            "host": self._host,
            "port": str(self._port),
            "password": self._password,
            "key.pattern": key_pattern,
            "infer.schema": "false",
        }

        def _load_sync() -> "DataFrame":
            try:
                return (
                    spark_session.read.format("org.apache.spark.sql.redis")
                    .schema(target_schema)
                    .options(**redis_config)
                    .load()
                )
            except Exception as e:
                logging.error(f"Failed to load data using spark-redis: {e}")
                return spark_session.createDataFrame([], target_schema)

        return await asyncio.to_thread(_load_sync)

    async def _load_table_fallback_spark(
        self, table_name: str, spark_session, target_schema, data_type
    ) -> "DataFrame":
        """Loads 'string' or 'json' tables using the
        non-scalable mapPartitions method."""
        msg = f"Using non-scalable `mapPartitions` loader for data_type '{data_type}'."
        msg += " This will be slow and may crash on large tables."
        logging.warning(msg)

        r = self._get_client()
        # Create a clean config dict to pass to workers
        # (Do NOT pass 'self' or objects containing sockets)
        redis_config = {
            "host": self._host,
            "port": self._port,
            "password": self._password,
        }
        num_slices = spark_session.sparkContext.defaultParallelism * 4

        key_pattern = f"{table_name.capitalize()}:*"
        if self._options.get("include_data_type_in_pk", False):
            key_pattern += f":{data_type}"

        keys = [key async for key in r.scan_iter(key_pattern)]
        if not keys:
            return spark_session.createDataFrame([], target_schema)

        keys_rdd = spark_session.sparkContext.parallelize(keys, numSlices=num_slices)

        # [CRITICAL FIX] Use RedisConnector class explicitly to avoid capturing 'self'
        data_rdd = keys_rdd.mapPartitions(
            lambda it: RedisConnector._fetch_redis_data_fallback(
                it, redis_config, data_type
            )
        )

        if data_rdd.isEmpty():
            return spark_session.createDataFrame([], target_schema)

        df = data_rdd.toDF()
        for field in target_schema.fields:
            if field.name in df.columns:
                df = df.withColumn(field.name, F.col(field.name).cast(field.dataType))
        return df

    async def _load_table_to_spark_df(
        self, table_name: str, spark_session
    ) -> "DataFrame":
        """
        [Sonar Refactor]
        Loads a table from Redis into a Spark DataFrame.
        Delegates to the correct helper based on data_type.
        """
        data_type = self.get_data_type()
        target_schema = self._get_spark_schema(table_name)
        if not target_schema:
            raise ValueError(f"No Spark schema for table {table_name}")

        if data_type == "hash":
            return await self._load_table_hash_spark(
                table_name, spark_session, target_schema, data_type
            )
        else:
            return await self._load_table_fallback_spark(
                table_name, spark_session, target_schema, data_type
            )

    # --- [SONARQUBE S3776 FIX] ---
    # Refactored join/group_by to use helper functions.

    async def _apply_spark_joins(
        self, joined_df: "DataFrame", joins: List[exp.Join], spark_session
    ) -> "DataFrame":
        """Applies all JOIN clauses to a Spark DataFrame."""
        for join_expr in joins:
            join_table_expr = join_expr.this
            join_table_name = join_table_expr.this.name
            join_table_alias = join_table_expr.alias_or_name

            df_to_join = (
                await self._load_table_to_spark_df(join_table_name, spark_session)
            ).alias(join_table_alias)

            join_condition = self._translate_expression_to_spark(
                join_expr.args.get("on")
            )
            join_type = join_expr.args.get("kind", "INNER").lower()

            joined_df = joined_df.join(df_to_join, on=join_condition, how=join_type)
        return joined_df

    def _apply_spark_where(
        self, df: "DataFrame", where: Optional[exp.Where]
    ) -> "DataFrame":
        """Applies a WHERE clause to a Spark DataFrame."""
        if where:
            filter_cond = self._translate_expression_to_spark(where.this)
            return df.filter(filter_cond)
        return df

    def _apply_spark_order_by(
        self, df: "DataFrame", order: Optional[exp.Order]
    ) -> "DataFrame":
        """Applies an ORDER BY clause to a Spark DataFrame."""
        if order:
            order_exprs = []
            for e in order.expressions:
                col = self._translate_expression_to_spark(e.this)
                direction = e.args.get("desc", False)
                order_exprs.append(col.desc() if direction else col.asc())
            return df.orderBy(*order_exprs)
        return df

    def _apply_spark_limit(
        self, df: "DataFrame", limit: Optional[exp.Limit]
    ) -> "DataFrame":
        """Applies a LIMIT clause to a Spark DataFrame."""
        if limit:
            limit_val = int(limit.this.this)
            return df.limit(limit_val)
        return df

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes a JOIN query using Spark.
        Delegates logic to helper methods.
        """
        spark = get_spark_session("Redis")
        if not spark:
            raise RuntimeError("PySpark is not available for JOINs.")

        # 1. Fetch the FROM table
        from_table_expr = ast.args.get("from").this
        from_table_name = from_table_expr.this.name
        from_table_alias = from_table_expr.alias_or_name

        df = (await self._load_table_to_spark_df(from_table_name, spark)).alias(
            from_table_alias
        )

        # 2. Apply Joins, Where, Order, Limit
        df = await self._apply_spark_joins(df, ast.args.get("joins", []), spark)
        df = self._apply_spark_where(df, ast.args.get("where"))
        df = self._apply_spark_order_by(df, ast.args.get("order"))
        df = self._apply_spark_limit(df, ast.args.get("limit"))

        # 3. Apply final SELECT
        select_expressions = [
            self._translate_expression_to_spark(e) for e in ast.expressions
        ]
        final_df = df.select(*select_expressions)

        # 4. Collect and return
        results = [row.asDict() for row in final_df.collect()]
        return [_camelize_keys(row) for row in results]

    def _apply_spark_group_by_aggs(
        self, df: "DataFrame", ast: exp.Select
    ) -> "DataFrame":
        """
        [Sonar Refactor S3776]
        Applies GROUP BY and Aggregation logic.
        Uses list comprehension to reduce complexity.
        """
        group_by_cols = [
            self._translate_expression_to_spark(e)
            for e in ast.args.get("group").expressions
        ]
        grouped_df = df.groupBy(*group_by_cols)

        # [SONAR REFACTOR S3776] Replaced loop with list comprehension
        agg_expressions = [
            self._translate_expression_to_spark(expr) for expr in ast.expressions
        ]

        return grouped_df.agg(*agg_expressions)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes a GROUP BY query using Spark.
        Delegates logic to helper methods.
        """
        spark = get_spark_session("Redis")
        if not spark:
            msg = "PySpark is required for GROUP BY operations"
            raise RuntimeError(msg)

        # 1. Load data
        table_name = ast.find(exp.Table).name
        df = await self._load_table_to_spark_df(table_name, spark)
        if df.isEmpty():
            return []

        # 2. Apply Where, GroupBy/Agg, Order
        df = self._apply_spark_where(df, ast.args.get("where"))
        df = self._apply_spark_group_by_aggs(df, ast)
        df = self._apply_spark_order_by(df, ast.args.get("order"))

        # 3. Apply final SELECT
        final_cols = [e.alias_or_name for e in ast.expressions]
        final_df = df.select(*final_cols)

        results = [row.asDict() for row in final_df.collect()]
        return [_camelize_keys(row) for row in results]

    # --- [SONARQUBE S3776 FIX FOR aggregate] ---

    def _handle_empty_aggregate_result(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Helper for aggregate:
        Returns a default empty/zero state when no data is found.
        """
        logging.info("No data to aggregate")
        result = {}
        for expr in ast.expressions:
            alias = expr.alias_or_name
            # Set default value for aggregate functions
            is_agg = isinstance(expr.this, (exp.Sum, exp.Avg))
            result[alias] = Decimal("0.0") if is_agg else 0
        return [_camelize_keys(result)]

    def _handle_agg_count(
        self, agg_func: exp.Count, all_data: List[Dict[str, Any]]
    ) -> int:
        """
        [Sonar Refactor] Helper for aggregate:
        Calculates COUNT(*) or COUNT(column).
        """
        if agg_func.this.is_star:
            return len(all_data)

        # Handle COUNT(column)
        col_name = agg_func.this.name
        values = [
            row.get(col_name) for row in all_data if row.get(col_name) is not None
        ]
        return len(values)

    def _handle_agg_sum_avg(
        self, agg_func: exp.AggFunc, all_data: List[Dict[str, Any]]
    ) -> Decimal:
        """
        [Sonar Refactor] Helper for aggregate:
        Calculates SUM(expr) or AVG(expr).
        """
        # Evaluate the expression for all rows
        values = [self._evaluate_expression(agg_func.this, row) for row in all_data]
        # Filter out None values which might result from failed lookups
        values = [v for v in values if v is not None]

        if isinstance(agg_func, exp.Sum):
            return sum(values)
        if isinstance(agg_func, exp.Avg):
            return sum(values) / len(values) if values else Decimal("0.0")

        return Decimal("0.0")  # Should not be reached

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes an aggregate query without GROUP BY.
        Delegates logic to helper methods to reduce complexity.
        """
        logging.info("Aggregating on Redis")
        table_name = ast.find(exp.Table).name
        all_data = await self.get_all(table_name)

        if not all_data:
            return self._handle_empty_aggregate_result(ast)

        result_row = {}
        for expr in ast.expressions:
            # Ensure we are dealing with an aliased aggregate function
            if not (isinstance(expr, exp.Alias) and isinstance(expr.this, exp.AggFunc)):
                continue

            agg_func, alias = expr.this, expr.alias_or_name

            if isinstance(agg_func, exp.Count):
                result_row[alias] = self._handle_agg_count(agg_func, all_data)

            elif isinstance(agg_func, (exp.Sum, exp.Avg)):
                result_row[alias] = self._handle_agg_sum_avg(agg_func, all_data)

            # Note: MIN/MAX not implemented in original, so not added here.

        return [_camelize_keys(result_row)]

    # --- [SONARQUBE S3776 & S7493 FIX] ---
    # Refactored bulk_insert to reduce complexity and use async I/O.

    def _process_row_for_redis(
        self, line: List[str], cols: List[str], dynamic_model: Any
    ) -> Optional[Dict[str, Any]]:
        """
        [Sonar Refactor] Processes a single CSV line for Redis bulk insert.
        Returns a processed dict or None if validation fails or the row is empty.
        """
        if not line or len(line) < len(cols):
            return None
        try:
            row_dict = dict(zip(cols, line[: len(cols)]))
            validated_data = dynamic_model(**row_dict)
            return validated_data.model_dump()
        except ValidationError as e:
            msg = f"Skipping malformed row: {line}. Error: {e}"
            logging.warning(msg)
            return None

    async def _process_csv_batch_redis(
        self,
        file_path: str,
        cols: List[str],
        dynamic_model: Any,
    ) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """
        [Sonar Refactor] Asynchronously reads a CSV file, validates rows,
        and yields batches of processed data.
        """
        batch = []
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                reader = csv.reader(content.splitlines(), delimiter="|")
                for line in reader:
                    processed_row = self._process_row_for_redis(
                        line, cols, dynamic_model
                    )
                    if processed_row:
                        batch.append(processed_row)
                        # Yield one by one for pipeline
                        yield processed_row

        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Error during CSV processing for {file_path}: {e}")
            raise

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        [Sonar Refactor] Bulk inserts data from a file into the specified table.
        Uses async I/O and delegates row processing to helpers.
        """
        r = self._get_client()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            raise ValueError(f"No schema for table: {table_name}")

        columns, pk_info = list(schema["columns"].keys()), schema["pk"]
        dynamic_model = get_pydantic_model(table_name, schema)
        data_type = self.get_data_type()
        inserted_count = 0

        async with r.pipeline(transaction=False) as pipe:
            # Use the async generator to process batches
            async for payload in self._process_csv_batch_redis(
                file_path, columns, dynamic_model
            ):
                pk_val = (
                    ":".join([str(payload[k]) for k in pk_info])
                    if isinstance(pk_info, list)
                    else payload[pk_info]
                )
                key = f"{table_name.capitalize()}:{pk_val}"
                if self._options.get("include_data_type_in_pk", False):
                    key += f":{data_type}"

                str_payload = {k: str(v) for k, v in payload.items()}
                logging.info(f"Bulk insert in {data_type} mode with key {key}")

                if data_type == "string":
                    await pipe.set(key, json.dumps(str_payload))
                elif data_type == "json":
                    await pipe.json().set(key, "$", str_payload)
                else:
                    await pipe.hset(key, mapping=str_payload)
                inserted_count += 1

            await pipe.execute()

        return inserted_count

    # --- [SONARQUBE S3776 FIX] ---
    # Refactored _evaluate_expression to reduce complexity.

    def _eval_column(self, expression: exp.Column, row_data) -> Decimal:
        """Helper for _evaluate_expression: Handles Column nodes."""
        val = row_data.get(expression.sql())
        try:
            return Decimal(val) if val is not None else Decimal("0.0")
        except (InvalidOperation, TypeError):
            return Decimal("0.0")

    def _eval_literal(self, expression: exp.Literal, row_data) -> Decimal:
        """Helper for _evaluate_expression: Handles Literal nodes."""
        return Decimal(expression.this)

    def _eval_paren(self, expression: exp.Paren, row_data) -> Decimal:
        """Helper for _evaluate_expression: Handles Paren nodes."""
        return self._evaluate_expression(expression.this, row_data)

    def _eval_binary(self, expression: exp.Binary, row_data) -> Decimal:
        """Helper for _evaluate_expression: Handles Binary nodes."""
        left_val = self._evaluate_expression(expression.left, row_data)
        right_val = self._evaluate_expression(expression.right, row_data)

        op_map = {
            exp.Mul: lambda a, b: a * b,
            exp.Sub: lambda a, b: a - b,
            exp.Add: lambda a, b: a + b,
        }
        op_func = op_map.get(type(expression))
        if op_func:
            return op_func(left_val, right_val)

        raise NotImplementedError(f"Unsupported binary expression: {type(expression)}")

    def _evaluate_expression(self, expression, row_data):
        """
        [Sonar Refactor]
        Evaluates a sqlglot Expression against a row of data.
        Delegates to helper methods to reduce cognitive complexity.
        """
        if isinstance(expression, exp.Binary):
            return self._eval_binary(expression, row_data)

        evaluator_map = {
            exp.Column: self._eval_column,
            exp.Literal: self._eval_literal,
            exp.Paren: self._eval_paren,
        }
        evaluator = evaluator_map.get(type(expression))

        if evaluator:
            return evaluator(expression, row_data)

        raise NotImplementedError(
            f"Unsupported expression: {type(expression)}"
        )  # noqa: E501
