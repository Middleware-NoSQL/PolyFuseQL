import os
import sys
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
import threading

# Configuration
CASS_HOST = os.getenv("CASSANDRA_HOST", "cassandra")
CASS_PORT = int(os.getenv("CASSANDRA_PORT", 9042))
CASS_USER = os.getenv("CASSANDRA_USER", "cassandra")
CASS_PASS = os.getenv("CASSANDRA_PASSWORD", "cassandra")
KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "tpch")
DATA_DIR = "/data"

# Schema Definitions matching User JSON
DDL = [
    f"""CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
         WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}};""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.region (
        r_regionkey int PRIMARY KEY,
        r_name text,
        r_comment text
    );""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.nation (
        n_nationkey int PRIMARY KEY,
        n_name text,
        n_regionkey int,
        n_comment text
    );""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.part (
        p_partkey int PRIMARY KEY,
        p_name text,
        p_mfgr text,
        p_brand text,
        p_type text,
        p_size int,
        p_container text,
        p_retailprice float,
        p_comment text
    );""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.supplier (
        s_suppkey int PRIMARY KEY,
        s_name text,
        s_address text,
        s_nationkey int,
        s_phone text,
        s_acctbal float,
        s_comment text
    );""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.partsupp (
        ps_partkey int,
        ps_suppkey int,
        ps_availqty int,
        ps_supplycost float,
        ps_comment text,
        PRIMARY KEY (ps_partkey, ps_suppkey)
    );""",
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.customer (
        c_custkey int PRIMARY KEY,
        c_name text,
        c_address text,
        c_nationkey int,
        c_phone text,
        c_acctbal float,
        c_mktsegment text,
        c_comment text
    );""",
    # Partitioning by orderkey (simplified from JSON 'pk: o_orderkey')
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.orders (
        o_orderkey int PRIMARY KEY,
        o_custkey int,
        o_orderstatus text,
        o_totalprice float,
        o_orderdate date,
        o_orderpriority text,
        o_clerk text,
        o_shippriority int,
        o_comment text
    );""",
    # Partitioning by orderkey, linenumber (Composite PK)
    f"""CREATE TABLE IF NOT EXISTS {KEYSPACE}.lineitem (
        l_orderkey int,
        l_partkey int,
        l_suppkey int,
        l_linenumber int,
        l_quantity float,
        l_extendedprice float,
        l_discount float,
        l_tax float,
        l_returnflag text,
        l_linestatus text,
        l_shipdate date,
        l_commitdate date,
        l_receiptdate date,
        l_shipinstruct text,
        l_shipmode text,
        l_comment text,
        PRIMARY KEY (l_orderkey, l_linenumber)
    );""",
]

PREPARED_STMTS = {}


def setup_schema(session):
    print("Setting up Schema...")
    for stmt in DDL:
        session.execute(stmt)

    # Prepare INSERT statements
    query = f"INSERT INTO {KEYSPACE}.region "
    query += "(r_regionkey, r_name, r_comment) "
    query += "VALUES (?, ?, ?)"

    PREPARED_STMTS["region"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.nation "
    query += "(n_nationkey, n_name, n_regionkey, n_comment) "
    query += "VALUES (?, ?, ?, ?)"

    PREPARED_STMTS["nation"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.part "
    query += "(p_partkey, p_name, p_mfgr, p_brand, p_type, "
    query += "p_size, p_container, p_retailprice, p_comment) "
    query += "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"

    PREPARED_STMTS["part"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.supplier "
    query += "(s_suppkey, s_name, s_address, s_nationkey, "
    query += "s_phone, s_acctbal, s_comment) "
    query += "VALUES (?, ?, ?, ?, ?, ?, ?)"

    PREPARED_STMTS["supplier"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.partsupp "
    query += "(ps_partkey, ps_suppkey, ps_availqty, "
    query += "ps_supplycost, ps_comment) "
    query += "VALUES (?, ?, ?, ?, ?)"

    PREPARED_STMTS["partsupp"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.customer "
    query += "(c_custkey, c_name, c_address, c_nationkey, "
    query += "c_phone, c_acctbal, c_mktsegment, c_comment) "
    query += "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"

    PREPARED_STMTS["customer"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.orders "
    query += "(o_orderkey, o_custkey, o_orderstatus, "
    query += "o_totalprice, o_orderdate, o_orderpriority, "
    query += "o_clerk, o_shippriority, o_comment) "
    query += "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"

    PREPARED_STMTS["orders"] = session.prepare(query)
    query = f"INSERT INTO {KEYSPACE}.lineitem "
    query += "(l_orderkey, l_partkey, l_suppkey, l_linenumber, "
    query += "l_quantity, l_extendedprice, l_discount, l_tax, "
    query += "l_returnflag, l_linestatus, l_shipdate, l_commitdate, "
    query += "l_receiptdate, l_shipinstruct, l_shipmode, l_comment) "
    query += "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

    PREPARED_STMTS["lineitem"] = session.prepare(query)


def parse_and_bind(table, parts):
    try:
        if table == "region":
            return [int(parts[0]), parts[1], parts[2]]
        elif table == "nation":
            return [int(parts[0]), parts[1], int(parts[2]), parts[3]]
        elif table == "part":
            return [
                int(parts[0]),
                parts[1],
                parts[2],
                parts[3],
                parts[4],
                int(parts[5]),
                parts[6],
                float(parts[7]),
                parts[8],
            ]
        elif table == "supplier":
            return [
                int(parts[0]),
                parts[1],
                parts[2],
                int(parts[3]),
                parts[4],
                float(parts[5]),
                parts[6],
            ]
        elif table == "partsupp":
            return [
                int(parts[0]),
                int(parts[1]),
                int(parts[2]),
                float(parts[3]),
                parts[4],
            ]
        elif table == "customer":
            return [
                int(parts[0]),
                parts[1],
                parts[2],
                int(parts[3]),
                parts[4],
                float(parts[5]),
                parts[6],
                parts[7],
            ]
        elif table == "orders":
            return [
                int(parts[0]),
                int(parts[1]),
                parts[2],
                float(parts[3]),
                parts[4],
                parts[5],
                parts[6],
                int(parts[7]),
                parts[8],
            ]
        elif table == "lineitem":
            return [
                int(parts[0]),
                int(parts[1]),
                int(parts[2]),
                int(parts[3]),
                float(parts[4]),
                float(parts[5]),
                float(parts[6]),
                float(parts[7]),
                parts[8],
                parts[9],
                parts[10],
                parts[11],
                parts[12],
                parts[13],
                parts[14],
                parts[15],
            ]
    except Exception:
        return None


def load_table(session, table_name):
    file_path = os.path.join(DATA_DIR, f"{table_name}.tbl")
    if not os.path.exists(file_path):
        print(f"Skipping {table_name}: File not found.")
        return

    print(f"Loading {table_name}...")

    # Truncate table before load
    try:
        session.execute(f"TRUNCATE {KEYSPACE}.{table_name}")
    except Exception as e:
        print(f"Warning truncating {table_name}: {e}")

    statement = PREPARED_STMTS[table_name]
    concurrency_limit = 100
    sem = threading.Semaphore(concurrency_limit)

    def handle_error(e):
        print(f"Insert Error: {e}")
        sem.release()

    def handle_success(result):
        sem.release()

    count = 0
    with open(file_path, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts and parts[-1] == "":
                parts.pop()

            data = parse_and_bind(table_name, parts)
            if data:
                sem.acquire()
                future = session.execute_async(statement, data)
                future.add_callbacks(handle_success, handle_error)
                count += 1
                if count % 2000 == 0:
                    print(f"Queued {count} rows...", end="\r")

    # Wait for remaining queries
    for _ in range(concurrency_limit):
        sem.acquire()

    print(f"\n✅ Loaded {count} records into '{table_name}'.")


if __name__ == "__main__":
    print(f"Connecting to Cassandra at {CASS_HOST}:{CASS_PORT}...")
    try:
        auth_provider = PlainTextAuthProvider(username=CASS_USER, password=CASS_PASS)
        cluster = Cluster([CASS_HOST], port=CASS_PORT, auth_provider=auth_provider)
        session = cluster.connect()

        setup_schema(session)

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
            load_table(session, table)

        cluster.shutdown()

    except Exception as e:
        print(f"❌ Error loading Cassandra: {e}")
        sys.exit(1)
