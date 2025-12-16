import os
from pymongo import MongoClient
import sys
from datetime import datetime

# Configuration
MONGO_HOST = os.getenv("MONGO_HOST", "mongodb")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27018))
MONGO_USER = os.getenv("MONGO_INITDB_ROOT_USERNAME", "root")
MONGO_PASS = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "example")
DB_NAME = os.getenv("MONGO_DB_NAME", "tpch")

DATA_DIR = "/data"


def get_file_path(table_name):
    return os.path.join(DATA_DIR, f"{table_name}.tbl")


def parse_row(table, parts):
    """Parses a row into a dictionary using the provided JSON schema names."""
    try:
        if table == "region":
            return {
                "r_regionkey": int(parts[0]),
                "r_name": parts[1],
                "r_comment": parts[2],
            }
        elif table == "nation":
            return {
                "n_nationkey": int(parts[0]),
                "n_name": parts[1],
                "n_regionkey": int(parts[2]),
                "n_comment": parts[3],
            }
        elif table == "part":
            return {
                "p_partkey": int(parts[0]),
                "p_name": parts[1],
                "p_mfgr": parts[2],
                "p_brand": parts[3],
                "p_type": parts[4],
                "p_size": int(parts[5]),
                "p_container": parts[6],
                "p_retailprice": float(parts[7]),
                "p_comment": parts[8],
            }
        elif table == "supplier":
            return {
                "s_suppkey": int(parts[0]),
                "s_name": parts[1],
                "s_address": parts[2],
                "s_nationkey": int(parts[3]),
                "s_phone": parts[4],
                "s_acctbal": float(parts[5]),
                "s_comment": parts[6],
            }
        elif table == "partsupp":
            return {
                "ps_partkey": int(parts[0]),
                "ps_suppkey": int(parts[1]),
                "ps_availqty": int(parts[2]),
                "ps_supplycost": float(parts[3]),
                "ps_comment": parts[4],
            }
        elif table == "customer":
            return {
                "c_custkey": int(parts[0]),
                "c_name": parts[1],
                "c_address": parts[2],
                "c_nationkey": int(parts[3]),
                "c_phone": parts[4],
                "c_acctbal": float(parts[5]),
                "c_mktsegment": parts[6],
                "c_comment": parts[7],
            }
        elif table == "orders":
            return {
                "o_orderkey": int(parts[0]),
                "o_custkey": int(parts[1]),
                "o_orderstatus": parts[2],
                "o_totalprice": float(parts[3]),
                "o_orderdate": datetime.strptime(parts[4], "%Y-%m-%d"),
                "o_orderpriority": parts[5],
                "o_clerk": parts[6],
                "o_shippriority": int(parts[7]),
                "o_comment": parts[8],
            }
        elif table == "lineitem":
            return {
                "l_orderkey": int(parts[0]),
                "l_partkey": int(parts[1]),
                "l_suppkey": int(parts[2]),
                "l_linenumber": int(parts[3]),
                "l_quantity": float(parts[4]),
                "l_extendedprice": float(parts[5]),
                "l_discount": float(parts[6]),
                "l_tax": float(parts[7]),
                "l_returnflag": parts[8],
                "l_linestatus": parts[9],
                "l_shipdate": datetime.strptime(parts[10], "%Y-%m-%d"),
                "l_commitdate": datetime.strptime(parts[11], "%Y-%m-%d"),
                "l_receiptdate": datetime.strptime(parts[12], "%Y-%m-%d"),
                "l_shipinstruct": parts[13],
                "l_shipmode": parts[14],
                "l_comment": parts[15],
            }
    except (ValueError, IndexError):
        # print(f"Error parsing row in {table}: {e}")
        return None
    return None


def load_table(db, table_name, batch_size=2000):
    file_path = get_file_path(table_name)
    if not os.path.exists(file_path):
        print(f"Skipping {table_name}: File not found at {file_path}")
        return

    print(f"Loading {table_name}...")
    collection = db[table_name]

    # Clean existing data
    collection.drop()

    batch = []
    count = 0

    with open(file_path, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts and parts[-1] == "":
                parts.pop()

            doc = parse_row(table_name, parts)
            if doc:
                batch.append(doc)

            if len(batch) >= batch_size:
                collection.insert_many(batch)
                count += len(batch)
                batch = []
                print(f"Inserted {count} rows...", end="\r")

    if batch:
        collection.insert_many(batch)
        count += len(batch)

    print(f"\n✅ Loaded {count} records into '{table_name}' collection.")


if __name__ == "__main__":
    print(f"Connecting to MongoDB at {MONGO_HOST}:{MONGO_PORT}...")
    try:
        client = MongoClient(
            host=MONGO_HOST, port=MONGO_PORT, username=MONGO_USER, password=MONGO_PASS
        )
        db = client[DB_NAME]

        tables = [
            "region",
            "nation",
            "part",
            "supplier",
            "partsupp",
            "customer",
            "orders",
            "lineitem",
        ]

        for table in tables:
            load_table(db, table)

    except Exception as e:
        print(f"❌ Error loading MongoDB: {e}")
        sys.exit(1)
