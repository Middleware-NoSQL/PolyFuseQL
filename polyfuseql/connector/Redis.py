import csv
import json
import logging
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
    from pyspark.sql import functions as F
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
        self._host = settings.redis_host
        self._port = settings.redis_port
        self._password = settings.redis_password
        self._client: Optional[aioredis.Redis] = None

    def get_data_type(self) -> str:
        """Returns the current data type strategy for Redis operations."""
        return self._options.get("data_type", settings.redis_data_type)

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
        key = f"{entity.capitalize()}:{pk_val}:{self.get_data_type()}"

        data_type = self.get_data_type()
        raw_data = None
        if data_type == "string":
            raw_data_str = await r.get(key)
            if raw_data_str:
                raw_data = json.loads(raw_data_str)
        elif data_type == "json":
            raw_data = await r.json().get(key)
        else:  # 'hash' is the default
            raw_data = await r.hgetall(key)

        if not raw_data:
            return {}

        schema = self.catalogue.get_schema(entity)
        if not schema:
            return _camelize_keys(raw_data)

        DynamicModel = get_pydantic_model(entity, schema)
        try:
            # Pydantic expects camelCase keys
            validated_model = DynamicModel(**_camelize_keys(raw_data))
            return raw_data | validated_model.model_dump()
        except ValidationError:
            return _camelize_keys(raw_data)

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

        key = f"{entity.capitalize()}:{pk_val}:{self.get_data_type()}"
        str_payload = {k: str(v) for k, v in payload.items()}

        data_type = self.get_data_type()
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
        key = f"{entity.capitalize()}:{pk_val}:{self.get_data_type()}"
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
        key = f"{entity.capitalize()}:{pk_val}:{self.get_data_type()}"
        return await r.delete(key)

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        r = self._get_client()
        keys = [
            key
            async for key in r.scan_iter(
                f"{entity.capitalize()}:*:{self.get_data_type()}"
            )
        ]
        if not keys:
            return []
        pipe = r.pipeline()
        for key in keys:
            if self.get_data_type() == "hash":
                pipe.hgetall(key)
            else:
                pipe.get(key)
        results = await pipe.execute()
        return [dict(res) for res in results if res]

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
        msg = "Unsupported SQL expression for Spark "
        msg += f"translation: {type(expression)}"
        raise NotImplementedError(msg)

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        spark = get_spark_session()
        if not spark:
            raise NotImplementedError("PySpark is not available for JOINs.")
        msg = "PySpark JOIN logic is "
        msg += "not fully implemented yet."
        raise NotImplementedError(msg)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        spark = get_spark_session()
        if not spark:
            msg = "PySpark is required for GROUP BY "
            msg += "operations but is not available."
            raise RuntimeError(msg)

        table_name = ast.find(exp.Table).name
        r = self._get_client()
        keys = [
            key
            async for key in r.scan_iter(
                f"{table_name.capitalize()}:*:{self.get_data_type()}"
            )
        ]
        if not keys:
            return []

        num_slices = spark.sparkContext.defaultParallelism * 4
        keys_rdd = spark.sparkContext.parallelize(keys, numSlices=num_slices)
        redis_config = {
            "host": self._host,
            "port": self._port,
            "password": self._password,
        }

        data_type = self.get_data_type()

        def fetch_redis_data(iterator):
            import redis
            import json

            partition_keys = list(iterator)
            if not partition_keys:
                return iter([])
            r_sync = redis.Redis(**redis_config, decode_responses=True)
            pipe = r_sync.pipeline(transaction=False)
            for key in partition_keys:
                if data_type == "hash":
                    pipe.hgetall(key)
                elif data_type in ["string", "json"]:
                    pipe.get(key)

            results = pipe.execute()

            if data_type in ["string", "json"]:
                return [json.loads(res) for res in results if res]
            else:
                return iter(results)

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
                )  # noqa: E501

        if ast.args.get("where"):
            filter_cond = self._translate_expression_to_spark(
                ast.args["where"].this
            )  # noqa: E501
            df = df.filter(filter_cond)

        group_by_cols = [
            c.this.name for c in ast.args.get("group").expressions
        ]  # noqa: E501
        grouped_df = df.groupBy(*group_by_cols)

        agg_expressions = []
        final_cols = [e.alias_or_name for e in ast.expressions]
        for expr in ast.expressions:
            if isinstance(expr, exp.Alias) and isinstance(
                expr.this, exp.AggFunc
            ):  # noqa: E501
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
                        agg_expr = agg_expr.cast(DecimalType(38, 6))  # noqa
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
            ):  # noqa: E501
                agg_func, alias = expr.this, expr.alias_or_name
                if isinstance(agg_func, exp.Count):
                    result_row[alias] = len(all_data)
                    continue
                values = [
                    self._evaluate_expression(agg_func.this, row)
                    for row in all_data  # noqa: E501
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
                key = f"{table_name.capitalize()}:{pk_val}:{data_type}"
                str_payload = {k: str(v) for k, v in payload.items()}
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
