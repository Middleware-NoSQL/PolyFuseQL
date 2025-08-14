import json
import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
import redis.asyncio as aioredis
from sqlglot import exp
import itertools
import csv
from datetime import datetime, date
from pydantic import ValidationError


class RedisConnector(Connector):
    """Connector for Redis with persistent connection handling."""

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        r = self._get_client()
        keys = await r.keys(f"{entity.capitalize()}:*")
        if not keys:
            return []

        pipe = r.pipeline()
        for key in keys:
            await pipe.hgetall(key)

        results = await pipe.execute()
        return [dict(res) for res in results if res]

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options or {})
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "tpch")
        self._client: Optional[aioredis.Redis] = None

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

    def _get_client(self) -> aioredis.Redis:
        if not self._client:
            raise ConnectionError(
                "RedisConnector is not connected. Call connect() first."
            )
        return self._client

    async def ping(self) -> bool:
        r = self._get_client()
        return await r.ping()

    async def count(self, namespace: str) -> int:
        r = self._get_client()
        prfx = f"{namespace.capitalize()}:*"
        total = 0
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=prfx, count=1000)
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def get(
        self,
        namespace: str,
        pk_col: str,
        pk_val: Any,
        interpret_types: bool = True,  # noqa: F501
    ) -> Dict[str, Any]:
        r = self._get_client()
        key = f"{namespace.capitalize()}:{pk_val}"
        data_type = self._options.get("data_type", "hash")

        raw_data: Optional[Dict | str] = None
        match data_type:
            case "string":
                raw_str = await r.get(key)
                raw_data = json.loads(raw_str) if raw_str else None
            case "hash":
                raw_data = await r.hgetall(key)
            case "json":
                raw_data = await r.json().get(key)
            case _:
                raise NotImplementedError(f"Unsupported data type:{data_type}")

        if not raw_data or not interpret_types:
            return raw_data or {}

        schema = TPCH_SCHEMA.get(namespace.lower())
        if not schema:
            return raw_data

        dynamic_model = get_pydantic_model(namespace, schema)
        try:
            validated_model = dynamic_model(**raw_data)
            return validated_model.model_dump()
        except ValidationError as e:
            msg = f"Could not validate/cast data for key {key}. "
            msg += f"Returning raw. Error: {e}"
            logging.warning(msg)
            return raw_data

    async def insert(self, namespace: str, payload: Dict[str, Any]) -> Any:
        r = self._get_client()
        pk_col = self._options.get("pk", "id")
        pk_val = payload.get(pk_col)
        if not pk_val:
            pk_col_old = pk_col
            for key, value in payload.items():
                pk_col, pk_val = key, value
                break
            msg = (
                f"Primary key '{pk_col_old}' not found "
                f"in payload for Redis insert."
                f" Using the first column as id: {pk_col}"
            )
            logging.warning(msg)

        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")
        msg = f"Unknown data type: {data_type}"
        match data_type:
            case "string":
                await r.set(key, json.dumps(payload))
            case "hash":
                await r.hset(key, mapping=payload)
            case "json":
                await r.json().set(key, "$", payload)
            case _:
                raise NotImplementedError(msg)
        return {"status": "inserted", "key": key, "backend": "redis"}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        msg = "RedisConnector does not support raw SQL queries."
        raise NotImplementedError(msg)

    async def delete(self, namespace: str, pk_col: str, pk_val: Any) -> int:
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        logging.info("redis-delete-key", key)
        deleted_count = await r.delete(key)
        return deleted_count

    async def update(
        self, namespace: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")
        logging.info("redis-update-key", key)
        logging.info("redis-update-value", payload)
        if not await r.exists(key):
            return 0

        match data_type:
            case "string":
                raw = await r.get(key)
                if not raw:
                    return 0
                data = json.loads(raw)
                data.update(payload)
                await r.set(key, json.dumps(data))
                return 1
            case "hash":
                await r.hset(key, mapping=payload)
                return 1
            case "json":
                for field, value in payload.items():
                    await r.json().set(key, f"$.{field}", value)
                return 1
            case _:
                raise NotImplementedError(
                    f"Unsupported data type for update: {data_type}"
                )

    async def join(
        self, ast: exp.Select, interpret_numeric: bool = True
    ) -> List[Dict[str, Any]]:
        """Performs an application-side INNER JOIN on two Redis namespaces."""
        left_table_expr = ast.args.get("from").this
        join_expr = ast.args.get("joins")[0]
        right_table_expr = join_expr.this
        on_condition = join_expr.args.get("on")

        left_table = left_table_expr.this.name
        right_table = right_table_expr.this.name
        left_join_col = on_condition.this.this.name
        right_join_col = on_condition.expression.this.name

        left_rows = await self.get_all(left_table)
        right_rows = await self.get_all(right_table)

        right_map = {str(row.get(right_join_col)): row for row in right_rows}

        joined_results = []
        for left_row in left_rows:
            join_key = str(left_row.get(left_join_col))
            if join_key in right_map:
                joined_results.append({**left_row, **right_map[join_key]})

        return joined_results

    async def group_by(
        self, ast: exp.Select, interpret_numeric: bool = True
    ) -> List[Dict[str, Any]]:
        """Performs an application-side GROUP BY on a Redis namespace."""
        table_name = ast.find(exp.Table).name
        group_by_cols = [e.sql() for e in ast.args.get("group").expressions]

        all_data = await self.get_all(table_name)
        if not all_data:
            return []

        if ast.args.get("where"):
            where_expr = ast.args["where"].this
            if isinstance(where_expr, exp.LTE):
                col, date_val = where_expr.left.sql(), where_expr.right.sql()
                date_str = date_val.split("'")[1]
                threshold_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                all_data = [
                    row
                    for row in all_data
                    if datetime.strptime(row[col], "%Y-%m-%d").date()
                    <= threshold_date  # noqa: F501
                ]

        all_data.sort(key=lambda x: tuple(x.get(col) for col in group_by_cols))

        def _evaluate_expression(expression, row_data):
            if isinstance(expression, exp.Column):
                val = row_data.get(expression.sql())
                return float(val) if interpret_numeric else val
            if isinstance(expression, exp.Literal):
                return float(expression.this)
            if isinstance(expression, exp.Mul):
                return _evaluate_expression(
                    expression.left, row_data
                ) * _evaluate_expression(expression.right, row_data)
            if isinstance(expression, exp.Sub):
                return _evaluate_expression(
                    expression.left, row_data
                ) - _evaluate_expression(expression.right, row_data)
            if isinstance(expression, exp.Add):
                return _evaluate_expression(
                    expression.left, row_data
                ) + _evaluate_expression(expression.right, row_data)
            msg = f"Unsupported expression: {type(expression)}"
            raise NotImplementedError(msg)

        results = []
        for key, group_iter in itertools.groupby(
            all_data, key=lambda x: tuple(x.get(col) for col in group_by_cols)
        ):
            group = list(group_iter)
            result_row = dict(zip(group_by_cols, key))

            for expr in ast.expressions:
                if isinstance(expr, exp.Alias):
                    agg_func = expr.this
                    alias = expr.alias_or_name

                    if isinstance(agg_func, exp.Count):
                        result_row[alias] = len(group)
                    elif (
                        isinstance(agg_func, exp.AggFunc)
                        and agg_func.expressions  # noqa: F501
                    ):  # noqa: F501
                        func_name = agg_func.name.lower()
                        inner = agg_func.expressions[0]
                        values = [
                            _evaluate_expression(inner, row) for row in group
                        ]  # noqa: F501
                        if func_name == "sum":
                            result_row[alias] = sum(values)
                        elif func_name == "avg":
                            result_row[alias] = (
                                sum(values) / len(values) if values else 0
                            )
            results.append(result_row)
        return [_camelize_keys(row) for row in results]

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        r = self._get_client()
        if table_name.lower() == "lineitem":
            await r.flushdb()

        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            msg = f"No schema definition found for table: {table_name}"
            raise ValueError(msg)

        columns = schema["columns"]
        pk_info = schema["pk"]
        data_type = self._options.get("data_type", "hash")

        dynamic_model = get_pydantic_model(table_name, schema)

        inserted_count = 0
        with open(file_path, "r") as f:
            reader = csv.reader(f, delimiter="|")
            batch = []
            for row in reader:
                if not row or len(row) <= 1:
                    continue
                row = row[: len(columns)]
                if len(row) < len(columns):
                    continue

                try:
                    row_dict = dict(zip(columns, row))
                    validated_data = dynamic_model(**row_dict)
                    batch.append(validated_data.model_dump())
                    inserted_count += 1
                except ValidationError as e:
                    msg = "Skipping malformed row due to validation"
                    msg += f" error: {row}. Error: {e}"
                    logging.warning(msg)

        async with r.pipeline(transaction=False) as pipe:
            for payload in batch:
                if isinstance(pk_info, list):
                    pk_val = ":".join([str(payload[k]) for k in pk_info])
                else:
                    pk_val = payload[pk_info]

                key = f"{table_name.capitalize()}:{pk_val}"

                if data_type == "hash":
                    await pipe.hset(
                        key, mapping={k: str(v) for k, v in payload.items()}
                    )
                elif data_type == "string":
                    await pipe.set(key, json.dumps(payload, default=str))
                elif data_type == "json":
                    serializable_payload = {
                        k: (v.isoformat() if isinstance(v, date) else v)
                        for k, v in payload.items()
                    }
                    pipe.json().set(key, "$", serializable_payload)
            await pipe.execute()

        return inserted_count
