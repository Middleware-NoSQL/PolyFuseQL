import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
import redis.asyncio as aioredis
from sqlglot import exp, transpile
import csv
from datetime import datetime
from pydantic import ValidationError
from decimal import Decimal, InvalidOperation

# PySpark Integration
try:
    from pyspark.sql import SparkSession
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
    """Connector for Redis with persistent connection handling and
    PySpark for complex queries."""

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options or {})
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "tpch")
        self._client: Optional[aioredis.Redis] = None
        self.spark: Optional["SparkSession"] = self._init_spark()

    def _init_spark(self) -> Optional["SparkSession"]:
        """Initializes and returns a local SparkSession
        if PySpark is available."""
        if not SPARK_AVAILABLE:
            msg = "PySpark not found. Complex queries like JOIN "
            msg += "and GROUP BY will be slow and memory-intensive."
            logging.warning(msg)
            return None
        try:
            return (
                SparkSession.builder.appName("PolyFuseQL-RedisConnector")
                .master("local[*]")
                .config("spark.driver.memory", "4g")
                .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
                .getOrCreate()
            )
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

    async def get(self, ent: str, pk_col: str, pk_val: Any) -> Dict[str, Any]:
        r = self._get_client()
        key = f"{ent.capitalize()}:{pk_val}"
        raw_data = await r.hgetall(key)  # Assuming HASH for simplicity
        if not raw_data:
            return {}

        schema = TPCH_SCHEMA.get(ent.lower())
        if not schema:
            return raw_data

        DynamicModel = get_pydantic_model(ent, schema)
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

    async def query(self, sql: str, arg: tuple = None) -> List[dict[str, Any]]:
        msg = "RedisConnector does not support raw SQL queries."
        raise NotImplementedError(msg)

    def _get_spark_schema(self, table_name: str) -> Optional["StructType"]:
        sc_def = TPCH_SCHEMA.get(table_name.lower())
        if not sc_def:
            return None
        type_mapping = {
            "int": IntegerType(),
            "str": StringType(),
            "date": DateType(),
            "decimal": DecimalType(18, 4),
        }
        fields = [
            StructField(c_name, type_mapping.get(col_type, StringType()), True)
            for c_name, col_type in zip(sc_def["columns"], sc_def["types"])
        ]
        return StructType(fields)

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        if not self.spark:
            raise NotImplementedError("PySpark is not available for JOINs.")
        msg = "PySpark JOIN logic is not fully implemented yet."
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        if not self.spark:
            raise RuntimeError("PySpark is required for GROUP BY operations.")

        table_name = ast.find(exp.Table).name
        all_data = await self.get_all(table_name)
        if not all_data:
            return []

        spark_sc = self._get_spark_schema(table_name)
        if not spark_sc:
            raise ValueError(f"No Spark schema for table {table_name}")

        # Identify columns by their target Spark type
        date_cols = {
            f.name for f in spark_sc.fields if isinstance(f.dataType, DateType)
        }
        int_cols = {
            f.name
            for f in spark_sc.fields
            if isinstance(f.dataType, IntegerType)  # noqa:F501
        }
        decimal_cols = {
            f.name
            for f in spark_sc.fields
            if isinstance(f.dataType, DecimalType)  # noqa:F501
        }

        # Pre-process the raw string data from Redis to match the schema types
        for row in all_data:
            for col_name in date_cols:
                if row.get(col_name):
                    try:
                        row[col_name] = datetime.strptime(
                            row[col_name], "%Y-%m-%d"
                        ).date()
                    except (ValueError, TypeError):
                        row[col_name] = None
            for col_name in int_cols:
                if row.get(col_name):
                    try:
                        row[col_name] = int(row[col_name])
                    except (ValueError, TypeError):
                        row[col_name] = None
            for col_name in decimal_cols:
                if row.get(col_name):
                    try:
                        row[col_name] = Decimal(row[col_name])
                    except (InvalidOperation, TypeError):
                        row[col_name] = None

        df = self.spark.createDataFrame(all_data, schema=spark_sc)
        temp_view_name = f"{table_name}_view"
        df.createOrReplaceTempView(temp_view_name)

        original_sql = ast.sql(dialect="duckdb")
        spark_sql = transpile(original_sql, read="duckdb", write="spark")[0]
        spark_sql = spark_sql.replace(f"`{table_name}`", temp_view_name)
        spark_sql = spark_sql.replace(f'"{table_name}"', temp_view_name)
        spark_sql = spark_sql.replace(f" {table_name} ", f" {temp_view_name} ")

        result_df = self.spark.sql(spark_sql)
        results = [row.asDict() for row in result_df.collect()]
        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        table_name = ast.find(exp.Table).name
        data = await self.get_all(table_name)
        result_row = {}
        if not data:
            return [{}]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa:F501
                agg_func = expr.this
                alias = expr.alias_or_name

                if isinstance(agg_func, exp.Count):
                    result_row[alias] = len(data)
                    continue

                values = [self._eval_expr(agg_func.this, row) for row in data]

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
                        msg = f"Skipping malformed row: {row}. Error: {e}"
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

    def _eval_expr(self, expr, row_data):
        if isinstance(expr, exp.Column):
            val = row_data.get(expr.sql())
            try:
                return Decimal(val) if val is not None else Decimal("0.0")
            except (InvalidOperation, TypeError):
                return Decimal("0.0")
        if isinstance(expr, exp.Literal):
            return Decimal(expr.this)
        if isinstance(expr, exp.Mul):
            return self._eval_expr(expr.left, row_data) * self._eval_expr(
                expr.right, row_data
            )
        if isinstance(expr, exp.Sub):
            return self._eval_expr(expr.left, row_data) - self._eval_expr(
                expr.right, row_data
            )
        if isinstance(expr, exp.Add):
            return self._eval_expr(expr.left, row_data) + self._eval_expr(
                expr.right, row_data
            )
        if isinstance(expr, exp.Paren):
            return self._eval_expr(expr.this, row_data)
        raise NotImplementedError(f"Unsupported expression: {type(expr)}")
