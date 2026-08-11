# ruff: noqa E501

import csv
import json
import logging
import asyncio
import aiofiles
import time
from typing import Any, Dict, List, Optional, AsyncGenerator

import redis.asyncio as aioredis
from pydantic import ValidationError
from sqlglot import exp, parse_one

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings
from polyfuseql.connector.Connector import Connector
from polyfuseql.connector.SparkTranslator import SparkTranslator
from polyfuseql.utils.spark_manager import get_spark_session
from polyfuseql.utils.utils import get_pydantic_model, _camelize_keys

try:
    from pyspark.sql import functions as F, DataFrame, SparkSession
    from pyspark.sql.types import (
        StructType,
        StructField,
        StringType,
        DecimalType,
        DateType,
        IntegerType,
        LongType,
        DoubleType,
    )

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


class RedisConnector(Connector, SparkTranslator):
    """Connector for Redis implementing the full Connector interface."""

    def __init__(
        self,
        catalogue: Optional[Catalogue] = None,
        options: Optional[Dict] = None,
        is_local_implementation: bool = True,
    ) -> None:
        super().__init__(
            options=options,
            catalogue=catalogue,
            is_local_implementation=is_local_implementation
        )
        self._host = settings.redis.host
        self._port = settings.redis.port
        self._password = settings.redis.password
        self._client: Optional[aioredis.Redis] = None
        self._db = 0
        self._data_type = "hash"  # Options: 'string', 'json', 'hash'
        if options and "data_type" in options:
            self._data_type = options["data_type"]
        
        # State to track if we forced fallback due to error
        self._force_fallback = False

    # --- Lifecycle Methods ---

    async def connect(self):
        """Establish a persistent connection to the database."""
        if not self._client:
            logging.info(f"Connecting to Redis at {self._host}:{self._port} (DB: {self._db})...")
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                password=self._password,
                db=self._db,
                decode_responses=False,
            )
        return self._client

    async def disconnect(self):
        """Close the persistent connection."""
        if self._client:
            logging.info("Closing Redis connection...")
            await self._client.close()
            self._client = None
    
    # helper for internal use (legacy support)
    async def get_connection(self) -> Any:
        return await self.connect()
    
    async def close(self) -> None:
        await self.disconnect()

    async def ping(self) -> bool:
        """Check connection health."""
        try:
            client = await self.connect()
            return await client.ping()
        except Exception:
            return False

    # --- DDL Methods ---

    async def create_table(self, table_name: str, schema: Dict[str, Any]) -> None:
        pass

    async def delete_table(self, table_name: str) -> None:
        logging.info(f"Deleting table '{table_name}' from Redis...")
        client = await self.connect()
        cursor = b"0"
        total_deleted = 0
        while True:
            cursor, keys = await client.scan(cursor, match=f"{table_name}:*", count=5000)
            if keys:
                await client.delete(*keys)
                total_deleted += len(keys)
            if cursor == b"0":
                break
        logging.info(f"Deleted {total_deleted} keys for table '{table_name}'.")

    # --- Core CRUD Methods ---

    async def count(self, entity: str) -> int:
        client = await self.connect()
        count = 0
        cursor = b"0"
        while True:
            cursor, keys = await client.scan(cursor, match=f"{entity}:*", count=5000)
            count += len(keys)
            if cursor == b"0":
                break
        return count

    async def get(self, entity: str, pk_col: str, pk_val: Any) -> Dict[str, Any]:
        client = await self.connect()
        key = f"{entity}:{pk_val}"
        
        data = {}
        if self._data_type == "hash":
            raw = await client.hgetall(key)
            if raw:
                data = {k.decode('utf-8'): v.decode('utf-8') for k, v in raw.items()}
        elif self._data_type == "json":
            data = await client.json().get(key)
        else:
            val = await client.get(key)
            if val:
                try:
                    data = json.loads(val)
                except Exception:
                    pass
        return data

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        client = await self.connect()
        key = self._generate_key(entity, payload)

        if self._data_type == "hash":
            str_payload = {k: str(v) for k, v in payload.items() if v is not None}
            await client.hset(key, mapping=str_payload)
        elif self._data_type == "json":
            from decimal import Decimal
            from datetime import date, datetime
            def _default(obj):
                if isinstance(obj, Decimal): return float(obj)
                if isinstance(obj, (date, datetime)): return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")
            sanitized_payload = json.loads(json.dumps(payload, default=_default))
            await client.json().set(key, "$", sanitized_payload)
        else:
            from decimal import Decimal
            from datetime import date, datetime
            def _default(obj):
                if isinstance(obj, Decimal): return float(obj)
                if isinstance(obj, (date, datetime)): return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")
            str_payload = json.dumps(payload, default=_default)
            await client.set(key, str_payload)
        
        return key

    async def update(self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]) -> int:
        client = await self.connect()
        key = f"{entity}:{pk_val}"
        
        exists = await client.exists(key)
        if not exists:
            return 0

        if self._data_type == "hash":
            str_payload = {k: str(v) for k, v in payload.items() if v is not None}
            await client.hset(key, mapping=str_payload)
        else:
            from decimal import Decimal
            from datetime import date, datetime
            def _default(obj):
                if isinstance(obj, Decimal): return float(obj)
                if isinstance(obj, (date, datetime)): return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")
            sanitized_payload = json.loads(json.dumps(payload, default=_default))

            if self._data_type == "json":
                for k, v in sanitized_payload.items():
                    await client.json().set(key, f"$.{k}", v)
            else:
                val = await client.get(key)
                if val:
                    current = json.loads(val)
                    current.update(sanitized_payload)
                    await client.set(key, json.dumps(current))
        
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        client = await self.connect()
        key = f"{entity}:{pk_val}"
        return await client.delete(key)

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        if SPARK_AVAILABLE:
            return await self.query(f"SELECT * FROM {entity}")
        
        client = await self.connect()
        results = []
        cursor = b"0"
        while True:
            cursor, keys = await client.scan(cursor, match=f"{entity}:*")
            if cursor == b"0":
                break
        return results

    # --- Relational/Analytical Methods (Spark Backed) ---

    async def _ensure_tables_loaded(
        self, ast: exp.Expression, spark: SparkSession
    ) -> None:
        """
        Identifies all physical tables recursively in the AST and loads them
        into Spark Temp Views. Skips tables already loaded.
        """
        for table in ast.find_all(exp.Table):
            table_name = table.name
            
            # Handle case sensitivity check against catalogue
            cat_schema = self.catalogue.get_schema(table_name)
            if not cat_schema:
                if self.catalogue.get_schema(table_name.lower()):
                    table_name = table_name.lower()
                else:
                    logging.debug(f"Skipping '{table_name}': Not found in catalogue.")
                    continue

            # Force reload if we are in fallback mode to replace potentially broken native views
            if not self._force_fallback and spark.catalog.tableExists(table_name):
                continue

            df = await self._load_table_to_spark_df(table_name, spark)
            df.createOrReplaceTempView(table_name)

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self.query(ast.sql())

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self.query(ast.sql())

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        return await self.query(ast.sql())

    async def query(self, sql: str, params: tuple = None) -> List[dict[str, Any]]:
        """
        Executes a raw SQL query using PySpark.
        Includes robust retry logic to handle native connector failures.
        """
        if not SPARK_AVAILABLE:
            raise NotImplementedError("PySpark is required for executing SQL on Redis.")

        logging.info(f"--- Starting Redis Query Execution ---")
        logging.info(f"SQL: {sql[:200]}..." if len(sql) > 200 else f"SQL: {sql}")
        start_time = time.time()

        try:
            parsed = parse_one(sql)
        except Exception as e:
            logging.warning(f"SQL parsing failed: {e}")
            parsed = None

        spark = get_spark_session()

        # Attempt 1: Load tables (optimistically utilizing native connector if available)
        self._force_fallback = False
        if parsed:
            await self._ensure_tables_loaded(parsed, spark)

        try:
            df = spark.sql(sql)
            results = [row.asDict() for row in df.collect()]
            
            duration = time.time() - start_time
            logging.info(f"--- Query Completed in {duration:.2f}s. Rows returned: {len(results)} ---")
            return results
        except Exception as e:
            error_msg = str(e)
            # Check for common native connector failure signatures
            if "ClassCastException" in error_msg or "NumberFormatException" in error_msg:
                logging.warning(f"Query failed with native connector issue: {error_msg}")
                logging.info("⚠️ Activating FORCE FALLBACK mode and retrying query...")
                
                # Retry Logic:
                # 1. Set flag to skip native connector
                self._force_fallback = True
                
                # 2. Reload tables using fallback loader
                if parsed:
                    await self._ensure_tables_loaded(parsed, spark)
                
                # 3. Retry Query
                try:
                    df = spark.sql(sql)
                    results = [row.asDict() for row in df.collect()]
                    duration = time.time() - start_time
                    logging.info(f"--- Retry Successful (Fallback Mode) in {duration:.2f}s. Rows: {len(results)} ---")
                    return results
                except Exception as retry_e:
                    logging.error(f"Retry failed: {retry_e}")
                    raise retry_e
            else:
                logging.error(f"Spark execution failed: {e}")
                raise

    # --- Loading Logic (Analyzed from spark-redis snapshot) ---

    async def _resolve_key_pattern(self, table_name: str, data_type: str) -> str:
        """
        Determines the actual casing of the table name in Redis keys.
        Returns the key pattern (e.g. "Nation:*").
        """
        r = self._get_client()
        # Try lowercase first (standard for this benchmark)
        lower_pattern = f"{table_name.lower()}:*"
        async for _ in r.scan_iter(match=lower_pattern, count=1):
            return lower_pattern

        # Try Capitalized
        cap_pattern = f"{table_name.capitalize()}:*"
        async for _ in r.scan_iter(match=cap_pattern, count=1):
            return cap_pattern

        return lower_pattern  # Default

    async def _load_table_hash_spark(
        self, table_name: str, spark_session, target_schema, data_type
    ) -> Optional["DataFrame"]:
        """
        FAST PATH: Uses spark-redis connector.
        Returns None if loading fails to trigger fallback.
        """
        if self._force_fallback:
            logging.info(f"Skipping native load for '{table_name}' (Fallback Active)")
            return None

        logging.info(f"⚡ Using scalable `spark-redis` for table: {table_name}")

        key_pattern = await self._resolve_key_pattern(table_name, data_type)
        actual_table_name = key_pattern.split(":")[0]

        # [FIX] spark-redis uses 'auth' for password, NOT 'password'
        redis_config = {
            "host": self._host,
            "port": str(self._port),
            "table": actual_table_name, # Mandatory for spark-redis 3.1.0
            "infer.schema": "false",  # We provide schema
        }
        
        if self._password:
            redis_config["auth"] = self._password

        def _load_sync() -> "DataFrame":
            try:
                reader = spark_session.read.format("org.apache.spark.sql.redis") \
                    .schema(target_schema) \
                    .options(**redis_config)
                df = reader.load()
                # Trigger a small action to force the connector to connect/read
                # This ensures we catch errors (like ClassCastException) here
                # rather than later during the main SQL query.
                df.limit(1).count()
                return df
            except Exception as e:
                logging.warning(f"Native spark-redis load failed for '{table_name}'. Triggering fallback. Reason: {e}")
                return None

        return await asyncio.to_thread(_load_sync)

    async def _load_table_fallback_spark(
        self, table_name: str, spark_session, target_schema, data_type
    ) -> "DataFrame":
        """
        SLOW PATH: Manually scans keys and fetches data.
        Used for 'string' and 'json' types OR if native load fails.
        """
        msg = "🐢 Using SLOW `mapPartitions` fallback loader "
        msg += f"for table '{table_name}'."
        logging.warning(msg)

        r = self._get_client()
        
        redis_config = {
            "host": self._host,
            "port": self._port,
            "password": self._password,
        }

        key_pattern = await self._resolve_key_pattern(table_name, data_type)

        logging.info(f"Scanning Redis keys ({key_pattern})...")
        keys = [key async for key in r.scan_iter(key_pattern)]
        logging.info(f"Found {len(keys)} keys.")

        if not keys:
            return spark_session.createDataFrame([], target_schema)

        # [OPTIMIZATION]: Force a higher distribution slice to prevent a single core lock
        # By spreading the key list, we parallelize the CPU-intensive json.loads() calls
        num_slices = max(8, spark_session.sparkContext.defaultParallelism * 4)
        keys_rdd = spark_session.sparkContext.parallelize(keys, numSlices=num_slices)

        data_rdd = keys_rdd.mapPartitions(
            lambda it: RedisConnector._fetch_redis_data_fallback(
                it, redis_config, data_type, spark_json_mode=(data_type in ["string", "json"])
            )
        )

        # Create DataFrame from RDD
        if data_type in ["string", "json"]:
            df = spark_session.read.schema(target_schema).json(data_rdd)
        else:
            df = spark_session.createDataFrame(data_rdd, schema=target_schema)
        return df

    async def _load_table_to_spark_df(
        self, table_name: str, spark_session
    ) -> "DataFrame":
        """
        Loads a table from Redis into a Spark DataFrame.
        Attempts native first, then fallback.
        """
        data_type = self.get_data_type()
        target_schema = self._get_spark_schema(table_name)
        if not target_schema:
            raise ValueError(f"No Spark schema for table {table_name}")

        # Attempt Native Load if data type supports it (Hash)
        if data_type == "hash":
            df = await self._load_table_hash_spark(
                table_name, spark_session, target_schema, data_type
            )
            if df is not None:
                return df
            logging.info("Falling back to manual loader due to native load failure.")

        # Fallback Load
        return await self._load_table_fallback_spark(
            table_name, spark_session, target_schema, data_type
        )
    
    # --- [Static Workers for Fallback] ---

    @staticmethod
    def _process_redis_results(results: list, data_type: str, spark_json_mode: bool = False):
        """Worker-side processing of Redis results."""
        import json

        if data_type not in ["string", "json"]:
            # Convert bytes to string for Hash map keys/values
            # Redis Pipeline results for HGETALL are dictionaries
            decoded_results = []
            for res in results:
                if not res: continue
                # PySpark needs standard python types (str, int), not bytes
                decoded_results.append(res)
            return iter(decoded_results)

        valid_results = []
        for res in results:
            if not res: continue
            if spark_json_mode:
                if isinstance(res, dict):
                    valid_results.append(json.dumps(res))
                elif isinstance(res, bytes):
                    valid_results.append(res.decode("utf-8"))
                else:
                    valid_results.append(res)
            else:
                try:
                    valid_results.append(json.loads(res))
                except (json.JSONDecodeError, TypeError):
                    if isinstance(res, dict): valid_results.append(res)
        return iter(valid_results)

    @staticmethod
    def _fetch_redis_data_fallback(iterator, redis_config, data_type, spark_json_mode: bool = False):
        """Worker-side fetching of Redis data."""
        import redis

        partition_keys = list(iterator)
        if not partition_keys:
            return iter([])

        r_sync = redis.Redis(**redis_config, decode_responses=True)
        
        # [OPTIMIZATION]: BATCH THE PIPELINE EXECUTIONS
        # Loading 60,000 commands into a single pipeline locks memory and CPU
        results = []
        batch_size = 5000
        
        for i in range(0, len(partition_keys), batch_size):
            pipe = r_sync.pipeline(transaction=False)
            batch_keys = partition_keys[i:i + batch_size]
            
            for key in batch_keys:
                if data_type == "hash":
                    pipe.hgetall(key)
                elif data_type == "json":
                    pipe.json().get(key)
                else:
                    pipe.get(key)
            
            # Execute and extend results array per batch chunk to keep memory footprint light
            results.extend(pipe.execute())

        r_sync.close()

        return RedisConnector._process_redis_results(results, data_type, spark_json_mode)
    
    # --- Helper Getters ---

    def get_data_type(self) -> str:
        return self._data_type

    def _get_client(self) -> aioredis.Redis:
        if not self._client:
            raise ConnectionError("RedisConnector is not connected. Call connect() first.")
        return self._client

    def _get_spark_schema(self, table_name: str) -> Optional["StructType"]:
        """Converts Catalogue schema to Spark StructType."""
        if not SPARK_AVAILABLE or not self.catalogue:
            return None
            
        sch_def = self.catalogue.get_schema(table_name)
        if not sch_def:
            sch_def = self.catalogue.get_schema(table_name.lower())
        if not sch_def:
            return None
            
        fields = []
        for c_name, c_type in sch_def["columns"].items():
            t_str = str(c_type).lower()
            if "date" in t_str:
                fields.append(StructField(c_name, DateType(), True))
            elif "decimal" in t_str:
                fields.append(StructField(c_name, DoubleType(), True))
            elif "int" in t_str:
                fields.append(StructField(c_name, LongType(), True))
            elif "long" in t_str or "bigint" in t_str:
                fields.append(StructField(c_name, LongType(), True))
            elif "float" in t_str or "double" in t_str:
                fields.append(StructField(c_name, DoubleType(), True))
            else:
                fields.append(StructField(c_name, StringType(), True))
            
        return StructType(fields)

    # --- Bulk Operations ---

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 10000
    ) -> int:
        print(f"Inserting {table_name}")
        r = self._get_client()
        schema = self.catalogue.get_schema(table_name)
        if not schema:
            raise ValueError(f"No schema for table: {table_name}")

        columns, pk_info = list(schema["columns"].keys()), schema["pk"]
        dynamic_model = get_pydantic_model(table_name, schema)
        data_type = self.get_data_type()
        sch_def = self.catalogue.get_schema(table_name)
        if not sch_def:
            sch_def = self.catalogue.get_schema(table_name.lower())
        double_cols = set()
        if sch_def:
            for c_name, c_type in sch_def["columns"].items():
                t_str = str(c_type).lower()
                if "decimal" in t_str or "float" in t_str or "double" in t_str:
                    double_cols.add(c_name)

        inserted_count = 0

        async with r.pipeline(transaction=False) as pipe:
            async for payload in self._process_csv_batch_redis(
                file_path, columns, dynamic_model
            ):
                pk_val = (
                    ":".join([str(payload[k]) for k in pk_info])
                    if isinstance(pk_info, list)
                    else payload[pk_info]
                )

                # Match the test loader logic: table:pk
                # (Lower cased because we pass lowercase table_name usually)
                key = f"{table_name.lower()}:{pk_val}"

                str_payload = {}
                for k, v in payload.items():
                    if type(v).__name__ in ['date', 'datetime']:
                        str_payload[k] = str(v)
                    elif k in double_cols and v is not None:
                        str_payload[k] = float(v)
                    elif type(v).__name__ == 'Decimal':
                        str_payload[k] = float(v)
                    else:
                        str_payload[k] = v

                if data_type == "string":
                    await pipe.set(key, json.dumps(str_payload))
                elif data_type == "json":
                    await pipe.json().set(key, "$", str_payload)
                else:
                    await pipe.hset(key, mapping=str_payload)
                inserted_count += 1

                # [OPTIMIZATION] Batch size defaults pushed to 10k to limit network trips
                if inserted_count % batch_size == 0:
                    await pipe.execute()

            await pipe.execute()

        return inserted_count

    # Helper for bulk_insert
    async def _process_csv_batch_redis(
        self,
        file_path: str,
        cols: List[str],
        dynamic_model: Any,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                # Handle potential trailing newlines/pipes
                lines = [line for line in content.splitlines() if line.strip()]
                reader = csv.reader(lines, delimiter="|")
                for line in reader:
                    # TPC-H files sometimes have a trailing empty column due
                    # to trailing pipe
                    if len(line) > len(cols):
                        line = line[: len(cols)]

                    processed_row = self._process_row_for_redis(
                        line, cols, dynamic_model
                    )
                    if processed_row:
                        yield processed_row
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise
            
    def _process_row_for_redis(
        self, line: List[str], cols: List[str], dynamic_model: Any
    ) -> Optional[Dict[str, Any]]:
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

    def _generate_key(self, table: str, data: Dict[str, Any]) -> str:
        """Deterministic key generation strategy."""
        table_lower = table.lower()
        suffix = ""

        if table_lower == "lineitem" and "l_orderkey" in data and "l_linenumber" in data:
            suffix = f"{data['l_orderkey']}_{data['l_linenumber']}"
        elif table_lower == "partsupp" and "ps_partkey" in data and "ps_suppkey" in data:
            suffix = f"{data['ps_partkey']}_{data['ps_suppkey']}"
        else:
            pk = None
            if self.catalogue:
                try:
                    cat_schema = self.catalogue.get_schema(table)
                    if cat_schema:
                        pk = cat_schema.get('pk')
                except Exception:
                    pass

            if pk and isinstance(pk, str) and pk in data:
                suffix = str(data[pk])
            elif pk and isinstance(pk, list):
                parts = [str(data[k]) for k in pk if k in data]
                if len(parts) == len(pk):
                    suffix = "_".join(parts)

            if not suffix and self.catalogue:
                schema = self.catalogue.get_schema(table)
                if schema:
                    cols = schema.get('columns')
                    if cols and isinstance(cols, dict):
                        first_col = list(cols.keys())[0]
                        if first_col in data:
                            suffix = str(data[first_col])

        if not suffix:
            import uuid
            suffix = str(uuid.uuid4())

        return f"{table}:{suffix}"