import json
import logging
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.utils import env
import redis.asyncio as aioredis
from sqlglot import exp


class RedisConnector(Connector):
    """Connector for Redis with persistent connection handling."""

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        r = self._get_client()
        keys = await r.keys(f"{entity}:*")
        if not keys:
            return []
        print("REDIS-get_all-keys", keys)
        data_type = self._options.get("data_type", "string")
        msg = f"Unsupported data type:{data_type}"
        all_list = []
        for key in keys:
            match data_type:
                case "string":
                    raw = await r.get(key)
                    all_list.append(json.loads(raw) if raw else {})
                case "hash":
                    raw_hash = await r.hgetall(key)
                    all_list.append(raw_hash if raw_hash else {})
                case "json":
                    raw_json = await r.json().get(key)
                    all_list.append(raw_json if raw_json else {})
                case _:
                    raise NotImplementedError(msg)
        return all_list

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        self._host = env("REDIS_HOST", "localhost")
        self._port = int(env("REDIS_PORT", "6379"))
        self._password = env("REDIS_PASSWORD", "northwind")
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
        prefix = f"{namespace.lower()}:*"
        total = 0
        cursor = 0
        while True:
            cur = await r.scan(cursor=cursor, match=prefix, count=1000)
            cursor, keys = cur
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def get(
        self, namespace: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")

        match data_type:
            case "string":
                raw = await r.get(key)
                return json.loads(raw) if raw else {}
            case "hash":
                raw_hash = await r.hgetall(key)
                return raw_hash
            case "json":
                raw_json = await r.json().get(key)
                return raw_json if raw_json else {}
            case _:
                raise NotImplementedError(f"Unsupported data type:{data_type}")

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
        print("redis-delete-key", key)
        deleted_count = await r.delete(key)
        return deleted_count

    async def update(
        self, namespace: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        r = self._get_client()
        key = f"{namespace}:{pk_val}"
        data_type = self._options.get("data_type", "string")
        print("redis-update-key", key)
        print("redis-update-value", payload)
        if not await r.exists(key):
            return 0

        match data_type:
            case "string":
                # Inefficient Read-Modify-Write for string-encoded JSON
                raw = await r.get(key)
                print("redis-string-raw", raw)
                if not raw:
                    return 0
                data = json.loads(raw)
                print("redis-string-json", data)
                data.update(payload)
                print("redis-string-json-updated", data)
                await r.set(key, json.dumps(data))
                return 1
            case "hash":
                # Efficient partial update for HASH
                await r.hset(key, mapping=payload)
                return 1
            case "json":
                # Efficient partial update for JSON
                for field, value in payload.items():
                    await r.json().set(key, f"$.{field}", value)
                return 1
            case _:
                raise NotImplementedError(
                    f"Unsupported data type for update: {data_type}"
                )

            # In RedisConnector class

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Performs an application-side INNER JOIN on two Redis namespaces."""
        # 1. Deconstruct the AST using the same robust logic as Neo4j
        left_table_expr = ast.args.get("from").this
        join_expr = ast.args.get("joins")[0]
        right_table_expr = join_expr.this
        on_condition = join_expr.args.get("on")

        left_table = left_table_expr.this.name
        right_table = right_table_expr.this.name
        print("redis-join-left_table", left_table)
        print("redis-join-right_table", right_table)
        left_join_col = on_condition.this.this.name
        right_join_col = on_condition.expression.this.name
        print("redis-join-left_join_col", left_join_col)
        print("redis-join+right_join_col", right_join_col)

        # 2. Fetch all data from both namespaces
        left_rows = await self.get_all(left_table)
        right_rows = await self.get_all(right_table)

        print("redis-join-left_rows", left_rows)
        print("redis-join-right_rows", right_rows)

        # 3. Create a lookup map for the right side of the join for efficiency
        right_map = {str(row.get(right_join_col)): row for row in right_rows}
        where_clauses = []
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

        # 4. Iterate and join
        joined_results = []
        for left_row in left_rows:
            join_key = str(left_row.get(left_join_col))
            if join_key in right_map and join_key in params.values():
                right_row = right_map[join_key]
                # Merge the two dictionaries to form the joined row
                joined_results.append({**left_row, **right_row})

        return joined_results
