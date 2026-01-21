import logging
import csv
import os
import sys
from typing import Any, Dict, List, Optional

from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import BatchStatement, SimpleStatement

# --- Configuration Defaults ---
DEFAULT_CASSANDRA_HOSTS = ["localhost"]
DEFAULT_CASSANDRA_PORT = 9043  # Mapped port from docker-compose (internal is 9042)
DEFAULT_CASSANDRA_USER = "cassandra"
DEFAULT_CASSANDRA_PASS = "cassandra"
DEFAULT_KEYSPACE = "mykeyspace"
DEFAULT_DATA_DIR = "./docker/tpch-data"  # Directory containing .tbl files
BATCH_SIZE = 50  # Rows per batch

# --- Logging Setup ---
# Configure only if not already configured (to play nice when imported)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
logger = logging.getLogger(__name__)

# --- Schema Definition ---
# Maps table names to their columns and types.
# PK definition is separate.
SCHEMAS = {
    "region": {
        "columns": [("r_regionkey", "int"), ("r_name", "text"), ("r_comment", "text")],
        "pk": "r_regionkey",
    },
    "nation": {
        "columns": [
            ("n_nationkey", "int"),
            ("n_name", "text"),
            ("n_regionkey", "int"),
            ("n_comment", "text"),
        ],
        "pk": "n_nationkey",
    },
    "part": {
        "columns": [
            ("p_partkey", "int"),
            ("p_name", "text"),
            ("p_mfgr", "text"),
            ("p_brand", "text"),
            ("p_type", "text"),
            ("p_size", "int"),
            ("p_container", "text"),
            ("p_retailprice", "decimal"),
            ("p_comment", "text"),
        ],
        "pk": "p_partkey",
    },
    "supplier": {
        "columns": [
            ("s_suppkey", "int"),
            ("s_name", "text"),
            ("s_address", "text"),
            ("s_nationkey", "int"),
            ("s_phone", "text"),
            ("s_acctbal", "decimal"),
            ("s_comment", "text"),
        ],
        "pk": "s_suppkey",
    },
    "partsupp": {
        "columns": [
            ("ps_partkey", "int"),
            ("ps_suppkey", "int"),
            ("ps_availqty", "int"),
            ("ps_supplycost", "decimal"),
            ("ps_comment", "text"),
        ],
        # [FIX] Changed from "(ps_partkey, ps_suppkey)" to "ps_partkey, ps_suppkey"
        # This makes ps_partkey the Partition Key and ps_suppkey the Clustering Key.
        "pk": "ps_partkey, ps_suppkey",
    },
    "customer": {
        "columns": [
            ("c_custkey", "int"),
            ("c_name", "text"),
            ("c_address", "text"),
            ("c_nationkey", "int"),
            ("c_phone", "text"),
            ("c_acctbal", "decimal"),
            ("c_mktsegment", "text"),
            ("c_comment", "text"),
        ],
        "pk": "c_custkey",
    },
    "orders": {
        "columns": [
            ("o_orderkey", "int"),
            ("o_custkey", "int"),
            ("o_orderstatus", "text"),
            ("o_totalprice", "decimal"),
            ("o_orderdate", "date"),
            ("o_orderpriority", "text"),
            ("o_clerk", "text"),
            ("o_shippriority", "int"),
            ("o_comment", "text"),
        ],
        "pk": "o_orderkey",
    },
    "lineitem": {
        "columns": [
            ("l_orderkey", "int"),
            ("l_partkey", "int"),
            ("l_suppkey", "int"),
            ("l_linenumber", "int"),
            ("l_quantity", "decimal"),
            ("l_extendedprice", "decimal"),
            ("l_discount", "decimal"),
            ("l_tax", "decimal"),
            ("l_returnflag", "text"),
            ("l_linestatus", "text"),
            ("l_shipdate", "date"),
            ("l_commitdate", "date"),
            ("l_receiptdate", "date"),
            ("l_shipinstruct", "text"),
            ("l_shipmode", "text"),
            ("l_comment", "text"),
        ],
        # [FIX] Changed from "(l_orderkey, l_linenumber)" to "l_orderkey, l_linenumber"
        # This makes l_orderkey the Partition Key and l_linenumber the Clustering Key.
        # Queries on 'l_orderkey' will now be efficient direct lookups.
        "pk": "l_orderkey, l_linenumber",
    },
}


def get_session(hosts, port, user, password):
    """Establishes connection to Cassandra."""
    logger.info(f"Connecting to Cassandra at {hosts}:{port}...")
    auth_provider = PlainTextAuthProvider(username=user, password=password)
    cluster = Cluster(contact_points=hosts, port=port, auth_provider=auth_provider)
    session = cluster.connect()
    return cluster, session


def setup_schema(session, keyspace):
    """Creates Keyspace and Tables."""
    logger.info(f"Creating keyspace '{keyspace}' if not exists...")
    session.execute(
        f"""
        CREATE KEYSPACE IF NOT EXISTS {keyspace}
        WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
    """
    )
    session.set_keyspace(keyspace)

    for table, schema in SCHEMAS.items():
        logger.info(f"Setting up table: {table}")

        # Drop table to ensure fresh state and correct schema application
        session.execute(f"DROP TABLE IF EXISTS {table}")

        # Build CREATE TABLE statement
        cols_def = ", ".join([f"{c[0]} {c[1]}" for c in schema["columns"]])
        pk_def = schema["pk"]
        # With the fix: PRIMARY KEY (l_orderkey, l_linenumber) -> Valid partition/cluster split
        create_stmt = f"CREATE TABLE {table} ({cols_def}, PRIMARY KEY ({pk_def}))"

        logger.debug(f"Executing: {create_stmt}")
        session.execute(create_stmt)


def parse_and_cast_row(
    row: List[str], schema_columns: List[tuple], row_idx: int
) -> Optional[List[Any]]:
    """
    Parses a raw CSV row and casts values to Python types based on schema.
    Returns the cleaned row or None if parsing fails.
    """
    # TPC-H .tbl files often end with a '|', resulting in an empty last element.
    # We slice the row to match the number of expected columns.
    expected_cols = len(schema_columns)
    if len(row) > expected_cols:
        row = row[:expected_cols]

    if len(row) < expected_cols:
        logger.warning(
            f"Row {row_idx} missing columns. Expected {expected_cols}, got {len(row)}. Skipping."
        )
        return None

    cleaned_row = []
    for i, (col_name, col_type) in enumerate(schema_columns):
        val_str = row[i]
        try:
            if col_type == "int":
                # Handle cases where empty string might mean 0 or NULL
                if not val_str:
                    cleaned_row.append(None)
                else:
                    cleaned_row.append(int(val_str))
            elif col_type == "decimal" or col_type == "float":
                if not val_str:
                    cleaned_row.append(None)
                else:
                    cleaned_row.append(float(val_str))
            elif col_type == "date":
                # Cassandra driver handles string dates 'YYYY-MM-DD' fine
                cleaned_row.append(val_str)
            else:
                # text/varchar
                cleaned_row.append(val_str)
        except ValueError as e:
            logger.warning(
                f"Type error in row {row_idx}, col '{col_name}' ({col_type}): value='{val_str}'. Error: {e}"
            )
            return None

    return cleaned_row


def load_data(session, keyspace, data_dir):
    """Reads .tbl files and inserts data into Cassandra."""
    session.set_keyspace(keyspace)

    # Load tables in order (though order matters less for Cassandra than SQL)
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
        file_path = os.path.join(data_dir, f"{table}.tbl")
        if not os.path.exists(file_path):
            logger.error(f"Data file not found: {file_path}. Skipping table {table}.")
            continue

        logger.info(f"Loading table: {table} from {file_path}...")

        # Prepare the INSERT statement
        schema_cols = SCHEMAS[table]["columns"]
        col_names = [c[0] for c in schema_cols]
        placeholders = ", ".join(["?"] * len(col_names))
        col_names_str = ", ".join(col_names)

        insert_query = f"INSERT INTO {table} ({col_names_str}) VALUES ({placeholders})"
        prepared = session.prepare(insert_query)

        batch = BatchStatement()
        count = 0
        total_inserted = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")

                for row_idx, row in enumerate(reader):
                    # Skip empty lines
                    if not row:
                        continue

                    cleaned_values = parse_and_cast_row(row, schema_cols, row_idx)

                    if cleaned_values:
                        batch.add(prepared, cleaned_values)
                        count += 1

                    if count >= BATCH_SIZE:
                        try:
                            session.execute(batch)
                            total_inserted += count
                        except Exception as e:
                            logger.error(
                                f"Failed to execute batch for {table} at row {row_idx}: {e}"
                            )
                        finally:
                            batch = BatchStatement()
                            count = 0

                # Insert remaining
                if count > 0:
                    try:
                        session.execute(batch)
                        total_inserted += count
                    except Exception as e:
                        logger.error(f"Failed to execute final batch for {table}: {e}")

            logger.info(
                f"Finished loading {table}. Total rows inserted: {total_inserted}"
            )

        except Exception as e:
            logger.error(f"Critical error loading file {file_path}: {e}")


def run_load(
    keyspace=DEFAULT_KEYSPACE,
    data_dir=DEFAULT_DATA_DIR,
    hosts=DEFAULT_CASSANDRA_HOSTS,
    port=DEFAULT_CASSANDRA_PORT,
    user=DEFAULT_CASSANDRA_USER,
    password=DEFAULT_CASSANDRA_PASS,
):
    """Orchestrates the loading process."""
    cluster = None
    try:
        cluster, session = get_session(hosts, port, user, password)
        setup_schema(session, keyspace)
        load_data(session, keyspace, data_dir)
        logger.info("TPC-H Data Load Complete.")
    except Exception as e:
        logger.critical(f"Cassandra Loader failed: {e}")
        raise
    finally:
        if cluster:
            cluster.shutdown()


def main():
    try:
        run_load()
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
