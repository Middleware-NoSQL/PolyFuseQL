import os
import redis
import sys

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "tpch")
DATA_DIR = "/data"

# Schema Definition based on provided JSON
# Lists are ordered to match the TPC-H .tbl file structure
SCHEMAS = {
    "region": {
        "columns": ["r_regionkey", "r_name", "r_comment"],
        "pk": ["r_regionkey"],
    },
    "nation": {
        "columns": ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
        "pk": ["n_nationkey"],
    },
    "part": {
        "columns": [
            "p_partkey",
            "p_name",
            "p_mfgr",
            "p_brand",
            "p_type",
            "p_size",
            "p_container",
            "p_retailprice",
            "p_comment",
        ],
        "pk": ["p_partkey"],
    },
    "supplier": {
        "columns": [
            "s_suppkey",
            "s_name",
            "s_address",
            "s_nationkey",
            "s_phone",
            "s_acctbal",
            "s_comment",
        ],
        "pk": ["s_suppkey"],
    },
    "partsupp": {
        "columns": [
            "ps_partkey",
            "ps_suppkey",
            "ps_availqty",
            "ps_supplycost",
            "ps_comment",
        ],
        "pk": ["ps_partkey", "ps_suppkey"],
    },
    "customer": {
        "columns": [
            "c_custkey",
            "c_name",
            "c_address",
            "c_nationkey",
            "c_phone",
            "c_acctbal",
            "c_mktsegment",
            "c_comment",
        ],
        "pk": ["c_custkey"],
    },
    "orders": {
        "columns": [
            "o_orderkey",
            "o_custkey",
            "o_orderstatus",
            "o_totalprice",
            "o_orderdate",
            "o_orderpriority",
            "o_clerk",
            "o_shippriority",
            "o_comment",
        ],
        "pk": ["o_orderkey"],
    },
    "lineitem": {
        "columns": [
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_quantity",
            "l_extendedprice",
            "l_discount",
            "l_tax",
            "l_returnflag",
            "l_linestatus",
            "l_shipdate",
            "l_commitdate",
            "l_receiptdate",
            "l_shipinstruct",
            "l_shipmode",
            "l_comment",
        ],
        "pk": ["l_orderkey", "l_linenumber"],
    },
}


def load_table(r, table_name):
    if table_name not in SCHEMAS:
        print(f"Skipping {table_name}: No schema defined.")
        return

    file_path = os.path.join(DATA_DIR, f"{table_name}.tbl")
    if not os.path.exists(file_path):
        print(f"Skipping {table_name}: File not found at {file_path}")
        return

    print(f"Loading {table_name}...")

    schema = SCHEMAS[table_name]
    columns = schema["columns"]
    pks = schema["pk"]

    # Pre-calculate PK indices
    try:
        pk_indices = [columns.index(pk_col) for pk_col in pks]
    except ValueError as e:
        print(
            f"Schema Error for {table_name}: PK column not found in columns list. {e}"
        )
        return

    pipeline = r.pipeline()
    count = 0

    with open(file_path, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts and parts[-1] == "":
                parts.pop()

            if len(parts) != len(columns):
                # Simple mismatch check, though sometimes TPC-H has extra formatting
                pass

            # Construct Primary Key
            # e.g. lineitem:100:2 (Composite) or customer:5 (Simple)
            try:
                pk_values = [parts[i] for i in pk_indices]
                redis_key = f"{table_name}:{':'.join(pk_values)}"

                # Construct Data Hash using correct column names
                # We zip schema columns with file parts
                data = dict(zip(columns, parts))

                pipeline.hset(redis_key, mapping=data)
                count += 1
            except IndexError:
                continue

            if count % 2000 == 0:
                pipeline.execute()
                pipeline = r.pipeline()
                print(f"Queued {count} rows...", end="\r")

    pipeline.execute()
    print(f"\n✅ Loaded {count} records for {table_name}")


if __name__ == "__main__":
    print(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        r.ping()

        # Load all standard TPC-H tables
        for table in SCHEMAS.keys():
            load_table(r, table)

    except Exception as e:
        print(f"❌ Error loading Redis: {e}")
        sys.exit(1)
