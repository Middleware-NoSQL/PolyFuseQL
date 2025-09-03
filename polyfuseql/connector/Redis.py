import csv
import logging
import os
import sys
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from pydantic import ValidationError
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env, get_pydantic_model, _camelize_keys

try:
    from pyspark.sql import SparkSession, functions as F
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
    """Connector for Redis, now using the schema-aware Catalogue."""

    def __init__(
        self,
        options: Optional[Dict] = None,
        catalogue: Optional[Catalogue] = None,
    ) -> None:
        super().__init__(options or {}, catalogue)
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "tpch")
        self._client: Optional[aioredis.Redis] = None
        self.spark: Optional["SparkSession"] = None
        self._dependencies_zip: Optional[str] = None

    def _prepare_dependencies(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        zip_path = project_root / "dependencies.zip"
        self._dependencies_zip = str(zip_path)
        if zip_path.exists():
            return
        try:
            venv_path = Path(sys.prefix)
            site_packages = next(venv_path.glob("**/site-packages"))
            required_libs = ["redis", "async_timeout"]
            lib_paths = [site_packages / lib for lib in required_libs]
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for lib_path in lib_paths:
                    if not lib_path.exists():
                        msg = f"Could not find '{lib_path.name}' "
                        msg += "in site-packages."
                        raise FileNotFoundError(msg)
                    for file in lib_path.rglob("*"):
                        arcname = file.relative_to(site_packages)
                        zf.write(file, arcname)
        except Exception as e:
            logging.error(f"Failed to create dependencies zip file: {e}")
            self._dependencies_zip = None

    def _init_spark(self) -> Optional["SparkSession"]:
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
                builder = (
                    builder.config("spark.cores.max", "48")
                    .config("spark.driver.memory", "4g")
                    .config("spark.executor.memory", "3g")
                    .config("spark.sql.shuffle.partitions", "144")
                    .config("spark.network.timeout", "8000s")
                    .config("spark.executor.heartbeatInterval", "60s")
                )
            else:
                builder = builder.config("spark.driver.memory", "4g")

            spark_session = builder.getOrCreate()
            if "local" not in spark_master_url:
                self._prepare_dependencies()
                if self._dependencies_zip:
                    spark_session.sparkContext.addPyFile(
                        self._dependencies_zip
                    )  # noqa:F501
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

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self.spark:
            self.spark.stop()
            self.spark = None
        if self._dependencies_zip and os.path.exists(self._dependencies_zip):
            try:
                os.remove(self._dependencies_zip)
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
        cursor = "0"
        while cursor != 0:
            cursor, keys = await r.scan(cursor=cursor, match=prfx, count=1000)
            total += len(keys)
        return total

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa:F501
        r = self._get_client()
        key = f"{entity.capitalize()}:{pk_val}"
        raw_data = await r.hgetall(key)
        if not raw_data:
            return {}

        schema = self.catalogue.get_schema(entity)
        if not schema:
            return raw_data  # Return raw data if no schema is found

        DynamicModel = get_pydantic_model(entity, schema)
        try:
            validated_model = DynamicModel(**raw_data)
            return validated_model.model_dump()
        except ValidationError:
            return raw_data  # Return raw on validation failure

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        r = self._get_client()
        schema = self.catalogue.get_schema(entity)
        if not schema:
            raise ValueError(f"No schema for table: {entity}")

        pk_col = schema["pk"]
        if isinstance(pk_col, list):
            pk_val = ":".join(str(payload.get(k)) for k in pk_col)
        else:
            pk_val = payload.get(pk_col)

        if not pk_val:
            raise ValueError("Primary key value not found in payload.")

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
        keys = [key async for key in r.scan_iter(f"{entity.capitalize()}:*")]
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
        msg = "RedisConnector does not support "
        msg += "raw SQL queries."
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
            )  # noqa:F501
            for col_name, col_type in schema_def["columns"].items()
        ]
        return StructType(fields)

    def _translate_expression_to_spark(self, expression: exp.Expression):
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
            op_map = {
                exp.Mul: lambda a, b: a * b,
                exp.Sub: lambda a, b: a - b,
                exp.Add: lambda a, b: a + b,
                exp.LTE: lambda a, b: a <= b,
            }
            if type(expression) in op_map:
                return op_map[type(expression)](left, right)
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
        msg = "PySpark JOIN logic is "
        msg += "not fully implemented yet."
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        if self.spark is None:
            self.spark = self._init_spark()
        if not self.spark:
            raise RuntimeError("PySpark is required for GROUP BY operations.")

        table_name = ast.find(exp.Table).name
        r = self._get_client()
        keys = [
            key async for key in r.scan_iter(f"{table_name.capitalize()}:*")
        ]  # noqa:F501
        if not keys:
            return []

        num_slices = self.spark.sparkContext.defaultParallelism * 4
        keys_rdd = self.spark.sparkContext.parallelize(
            keys, numSlices=num_slices
        )  # noqa:F501
        redis_config = {
            "host": self._host,
            "port": self._port,
            "password": self._password,
        }

        def fetch_redis_data(iterator):
            import redis

            partition_keys = list(iterator)
            if not partition_keys:
                return iter([])
            r_sync = redis.Redis(**redis_config, decode_responses=True)
            pipe = r_sync.pipeline(transaction=False)
            for key in partition_keys:
                pipe.hgetall(key)
            return iter(pipe.execute())

        data_rdd = keys_rdd.mapPartitions(fetch_redis_data)
        if data_rdd.isEmpty():
            return []

        df = data_rdd.toDF()
        target_schema = self._get_spark_schema(table_name)
        if not target_schema:
            raise ValueError(f"No Spark schema for table {table_name}")

        for field in target_schema.fields:
            if field.name in df.columns:
                df = df.withColumn(
                    field.name, F.col(field.name).cast(field.dataType)
                )  # noqa:F501

        if ast.args.get("where"):
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa:F501
            df = df.filter(filter_cond)

        group_by_cols = [
            c.this.name for c in ast.args.get("group").expressions
        ]  # noqa:F501
        grouped_df = df.groupBy(*group_by_cols)

        agg_expressions = []
        final_cols = [e.alias_or_name for e in ast.expressions]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa:F501
                agg_func = expr.this
                alias = expr.alias_or_name
                inner_expr = self._translate_expression_to_spark(agg_func.this)
                agg_map = {
                    exp.Sum: F.sum,
                    exp.Avg: F.avg,
                    exp.Count: F.count,
                }
                if type(agg_func) in agg_map:
                    agg_expr = agg_map[type(agg_func)](inner_expr)
                    if type(agg_func) in [exp.Sum, exp.Avg]:
                        agg_expr = agg_expr.cast(DecimalType(38, 6))
                    agg_expressions.append(agg_expr.alias(alias))

        agg_df = grouped_df.agg(*agg_expressions)
        if ast.args.get("order"):
            order_cols = [c.this.name for c in ast.args["order"].expressions]
            agg_df = agg_df.orderBy(*order_cols)

        final_df = agg_df.select(*final_cols)
        results = [row.asDict() for row in final_df.collect()]
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
                agg_func, alias = expr.this, expr.alias_or_name
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
        )  # noqa:F501
