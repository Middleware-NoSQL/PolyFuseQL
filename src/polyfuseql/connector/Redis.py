import csv
import json
import logging
import asyncio  # Import asyncio for thread bridging
from ast import literal_eval
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from pydantic import ValidationError
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings
from polyfuseql.connector.Connector import Connector
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


class RedisConnector(Connector):
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
                raw_data = json.loads(raw_data_str)
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

        DynamicModel = get_pydantic_model(entity, schema)
        try:
            # Pydantic expects camelCase keys
            validated_model = DynamicModel(**raw_data)
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
        pipe = r.pipeline()
        for key in keys:
            logging.info(f"get-key: {key}")
            if self.get_data_type() == "hash":
                await pipe.hgetall(key)
            else:
                await pipe.get(key)
        results = await pipe.execute()
        logging.info(f"Results: {results}")
        return [dict(literal_eval(res)) for res in results if res]

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

    def _translate_expression_to_spark(self, expression: exp.Expression):
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
            try:
                # Try to cast to Decimal for numeric literals
                return F.lit(Decimal(expression.this))
            except InvalidOperation:
                # Fallback to string literal
                return F.lit(expression.this)

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
            return F.to_date(F.lit(expression.this.this))

        msg = "Unsupported SQL expression for Spark "
        msg += f"translation: {type(expression)}"
        raise NotImplementedError(msg)

    async def _load_table_to_spark_df(
        self, table_name: str, spark_session
    ) -> "DataFrame":
        """
        Loads a table from Redis into a Spark DataFrame.

        - If data_type is 'hash', it uses the scalable `spark-redis` connector.
        - If data_type is 'string' or 'json', it falls back to the
          less-scalable `mapPartitions` method which can handle custom types
          but suffers from a driver-side SCAN bottleneck.
        """
        data_type = self.get_data_type()
        target_schema = self._get_spark_schema(table_name)
        if not target_schema:
            raise ValueError(f"No Spark schema for table {table_name}")

        # ------------------------------------------------------------------
        # PATH 1: Scalable logic for 'hash' type
        # ------------------------------------------------------------------
        if data_type == "hash":
            logging.info(
                f"Using scalable `spark-redis` connector for 'hash' table: {table_name}"  # noqa:E501
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
                    df = (
                        spark_session.read.format("org.apache.spark.sql.redis")
                        .schema(target_schema)
                        .options(**redis_config)
                        .load()
                    )
                    return df
                except Exception as e:
                    logging.error(
                        f"Failed to load data using spark-redis: {e}"
                    )  # noqa:E501
                    return spark_session.createDataFrame([], target_schema)

            df = await asyncio.to_thread(_load_sync)
            return df

        # ------------------------------------------------------------------
        # PATH 2: Fallback logic for 'string' and 'json' types
        # ------------------------------------------------------------------
        else:
            msg = "Using non-scalable `mapPartitions` "
            msg += f"loader for data_type '{data_type}'."
            msg += " This will be slow and may crash on large tables."
            logging.warning(msg)
            r = self._get_client()
            redis_config = {
                "host": self._host,
                "port": self._port,
                "password": self._password,
            }
            num_slices = spark_session.sparkContext.defaultParallelism * 4
            # Pass data_type to the worker
            data_type_for_worker = data_type

            def fetch_redis_data(iterator):
                """(Worker-side) Fetches data for string/json/hash types."""
                import redis
                import json

                partition_keys = list(iterator)
                if not partition_keys:
                    return iter([])
                r_sync = redis.Redis(**redis_config, decode_responses=True)
                pipe = r_sync.pipeline(transaction=False)

                # Use the closure variable
                data_type = data_type_for_worker

                for key in partition_keys:
                    if data_type == "hash":
                        pipe.hgetall(key)
                    elif data_type in ["string", "json"]:
                        pipe.get(key)
                results = pipe.execute()

                if data_type in ["string", "json"]:
                    valid_results = []
                    for res in results:
                        if res:
                            try:
                                valid_results.append(json.loads(res))
                            except json.JSONDecodeError:
                                logging.warning(f"Could not decode JSON:{res}")
                    return iter(valid_results)
                else:
                    return iter(results)

            # This is the non-scalable part: scanning all keys on the driver.
            key_pattern = f"{table_name.capitalize()}:*"
            if self._options.get("include_data_type_in_pk", False):
                key_pattern += f":{data_type}"

            keys = [key async for key in r.scan_iter(key_pattern)]

            if not keys:
                return spark_session.createDataFrame([], target_schema)

            # Parallelize the *list of keys*
            keys_rdd = spark_session.sparkContext.parallelize(
                keys, numSlices=num_slices
            )
            data_rdd = keys_rdd.mapPartitions(fetch_redis_data)
            if data_rdd.isEmpty():
                return spark_session.createDataFrame([], target_schema)

            df = data_rdd.toDF()

            # Cast columns (needed for mapPartitions, not for spark-redis)
            for field in target_schema.fields:
                if field.name in df.columns:
                    df = df.withColumn(
                        field.name, F.col(field.name).cast(field.dataType)
                    )
            return df

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes a JOIN query using Spark.
        This method now delegates data loading to _load_table_to_spark_df.
        """
        spark = get_spark_session("Redis")
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

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        [Sonar Refactor] Executes a GROUP BY query using Spark.
        This method now delegates data loading to _load_table_to_spark_df.
        """
        spark = get_spark_session("Redis")
        if not spark:
            msg = "PySpark is required for GROUP BY "
            msg += "operations but is not available."
            raise RuntimeError(msg)

        # 1. Load the data using the refactored helper
        table_name = ast.find(exp.Table).name
        df = await self._load_table_to_spark_df(table_name, spark)

        if df.isEmpty():
            return []

        # 2. Apply WHERE
        if ast.args.get("where"):
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa: E501
            df = df.filter(filter_cond)

        # 3. Apply GROUP BY
        group_by_cols = [
            c.this.name for c in ast.args.get("group").expressions
        ]  # noqa: E501
        grouped_df = df.groupBy(*group_by_cols)

        # 4. Apply Aggregations
        agg_expressions = []
        final_cols = [e.alias_or_name for e in ast.expressions]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa: E501
                # Use the main translator for aggregate functions
                agg_expr = self._translate_expression_to_spark(expr.this)
                agg_expressions.append(agg_expr.alias(expr.alias))
            elif expr.is_star:
                # Handle COUNT(*)
                agg_expressions.append(F.count(F.lit(1)).alias("count_star"))
                final_cols = ["count_star"]
            else:
                # Add group_by cols to the final select
                col = self._translate_expression_to_spark(expr)
                agg_expressions.append(col)

        agg_df = grouped_df.agg(*agg_expressions)

        # 5. Apply ORDER BY
        if ast.args.get("order"):
            order_cols = []
            for e in ast.args["order"].expressions:
                # Use translator for consistency
                col = self._translate_expression_to_spark(e.this)
                direction = e.args.get("desc", False)
                order_cols.append(col.desc() if direction else col.asc())
            agg_df = agg_df.orderBy(*order_cols)

        # 6. Apply SELECT (final projection)
        final_df = agg_df.select(*final_cols)
        results = [row.asDict() for row in final_df.collect()]
        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        logging.info("Aggregating on Redis")
        table_name = ast.find(exp.Table).name
        all_data = await self.get_all(table_name)
        result_row = {}
        if not all_data:
            logging.info("No data to aggregate")
            return [{}]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa: E501
                agg_func, alias = expr.this, expr.alias_or_name
                if isinstance(agg_func, exp.Count):
                    if agg_func.this.is_star:
                        result_row[alias] = len(all_data)
                        continue
                    # Handle COUNT(column)
                    values = [
                        row.get(agg_func.this.name)
                        for row in all_data
                        if row.get(agg_func.this.name) is not None
                    ]
                    result_row[alias] = len(values)
                    continue

                # Handle SUM, AVG for expressions
                values = [
                    self._evaluate_expression(agg_func.this, row)
                    for row in all_data  # noqa: E501
                ]
                values = [v for v in values if v is not None]

                if isinstance(agg_func, exp.Sum):
                    result_row[alias] = sum(values)
                elif isinstance(agg_func, exp.Avg):
                    result_row[alias] = (
                        sum(values) / len(values) if values else Decimal("0.0")
                    )
        return [_camelize_keys(result_row)]

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        r = self._get_client()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            raise ValueError(f"No schema for table: {table_name}")

        columns, pk_info = list(schema["columns"].keys()), schema["pk"]
        dynamic_model = get_pydantic_model(table_name, schema)
        inserted_count, batch = 0, []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")
                for row in reader:
                    if not row or len(row) < len(columns):
                        continue
                    try:
                        row_dict = dict(zip(columns, row[: len(columns)]))
                        validated_data = dynamic_model(**row_dict)
                        batch.append(validated_data.model_dump())
                        inserted_count += 1
                    except ValidationError as e:
                        msg = "Skipping malformed row: "
                        msg += f"{row}. Error: {e}"
                        logging.warning(msg)
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            return 0

        data_type = self.get_data_type()
        async with r.pipeline(transaction=False) as pipe:
            for payload in batch:
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
            left_val = self._evaluate_expression(expression.left, row_data)
            right_val = self._evaluate_expression(expression.right, row_data)
            return left_val * right_val
        if isinstance(expression, exp.Sub):
            left_val = self._evaluate_expression(expression.left, row_data)
            right_val = self._evaluate_expression(expression.right, row_data)
            return left_val - right_val
        if isinstance(expression, exp.Add):
            left_val = self._evaluate_expression(expression.left, row_data)
            right_val = self._evaluate_expression(expression.right, row_data)
            return left_val + right_val
        if isinstance(expression, exp.Paren):
            return self._evaluate_expression(expression.this, row_data)
        raise NotImplementedError(
            f"Unsupported expression: {type(expression)}"
        )  # noqa: E501
