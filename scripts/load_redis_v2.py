import os
import json
import logging
import redis

# Configuration
TPCH_DATA_DIR = "./docker/tpch-data"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "tpch"  # Matches your config

# Schema definition to map TBL columns to dict keys
SCHEMAS = {
    "region": ["r_regionkey", "r_name", "r_comment"],
    "nation": ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
    "part": [
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
    "supplier": [
        "s_suppkey",
        "s_name",
        "s_address",
        "s_nationkey",
        "s_phone",
        "s_acctbal",
        "s_comment",
    ],
    "customer": [
        "c_custkey",
        "c_name",
        "c_address",
        "c_nationkey",
        "c_phone",
        "c_acctbal",
        "c_mktsegment",
        "c_comment",
    ],
    "orders": [
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
    "lineitem": [
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
}


def parse_file(filename, table_name):
    """Reads a .tbl file and yields dictionaries."""
    filepath = os.path.join(TPCH_DATA_DIR, filename)
    if not os.path.exists(filepath):
        logging.warning(f"File not found: {filepath}")
        return []

    data = []
    schema = SCHEMAS[table_name]

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("|")
                row = {}
                for i, col_name in enumerate(schema):
                    if i >= len(parts):
                        break
                    val = parts[i]
                    # Attempt numeric conversion
                    try:
                        if (
                            "key" in col_name
                            or "number" in col_name
                            or "size" in col_name
                            or "quantity" in col_name
                        ):
                            row[col_name] = int(val)
                        elif (
                            "price" in col_name
                            or "bal" in col_name
                            or "discount" in col_name
                            or "tax" in col_name
                        ):
                            row[col_name] = float(val)
                        else:
                            row[col_name] = val
                    except ValueError:
                        row[col_name] = val
                data.append(row)
    except Exception as e:
        logging.error(f"Error reading {filename}: {e}")

    return data


def repopulate_redis():
    """Connects to Redis, flushes DB, and loads all TPC-H tables as JSON."""
    logging.basicConfig(level=logging.INFO)

    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        r.ping()
        logging.info("Connected to Redis.")
    except Exception as e:
        logging.error(f"Could not connect to Redis: {e}")
        return

    logging.info("Flushing Redis database...")
    r.flushall()

    def batch_upload(table_name, key_gen_func, filename):
        data = parse_file(filename, table_name)
        if not data:
            logging.warning(f"No data for {table_name}, skipping.")
            return

        pipe = r.pipeline()
        count = 0
        total = 0

        logging.info(f"Loading {table_name}...")
        for row in data:
            key = key_gen_func(row)
            # CRITICAL: Store as JSON string, not raw value
            pipe.set(key, json.dumps(row))
            count += 1
            if count >= 2000:
                pipe.execute()
                total += count
                count = 0
                pipe = r.pipeline()

        if count > 0:
            pipe.execute()
            total += count

        logging.info(f"Finished loading {total} rows for {table_name}")

    # Load all tables required for Query 8
    # Using lowercase prefixes (e.g. 'region:1') to match Redis.py detection
    batch_upload("region", lambda x: f"region:{x['r_regionkey']}", "region.tbl")
    batch_upload("nation", lambda x: f"nation:{x['n_nationkey']}", "nation.tbl")
    batch_upload("part", lambda x: f"part:{x['p_partkey']}", "part.tbl")
    batch_upload("supplier", lambda x: f"supplier:{x['s_suppkey']}", "supplier.tbl")
    batch_upload("customer", lambda x: f"customer:{x['c_custkey']}", "customer.tbl")
    batch_upload("orders", lambda x: f"orders:{x['o_orderkey']}", "orders.tbl")
    # Lineitem composite key
    batch_upload(
        "lineitem",
        lambda x: f"lineitem:{x['l_orderkey']}:{x['l_linenumber']}",
        "lineitem.tbl",
    )


if __name__ == "__main__":
    repopulate_redis()
