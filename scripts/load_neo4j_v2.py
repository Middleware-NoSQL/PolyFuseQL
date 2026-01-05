import os
import logging
from neo4j import GraphDatabase, basic_auth
import sys

# Configuration
TPCH_DATA_DIR = "./docker/tpch-data"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

# Configure Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Schema definition to map TBL columns to dict keys (TPC-H Standard)
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
    "partsupp": [
        "ps_partkey",
        "ps_suppkey",
        "ps_availqty",
        "ps_supplycost",
        "ps_comment",
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
        logging.warning(f"File not found: {filepath}. Skipping table {table_name}.")
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
                    try:
                        if (
                            "key" in col_name
                            or "number" in col_name
                            or "size" in col_name
                            or "quantity" in col_name
                            or "qty" in col_name
                            or "shippriority" in col_name
                        ):
                            row[col_name] = int(val)
                        elif (
                            "price" in col_name
                            or "bal" in col_name
                            or "discount" in col_name
                            or "tax" in col_name
                            or "cost" in col_name
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


def repopulate_neo4j():
    """Connects to Neo4j, flushes DB, and loads all TPC-H tables as Nodes."""
    driver = None
    try:
        driver = GraphDatabase.driver(
            NEO4J_URI, auth=basic_auth(NEO4J_USER, NEO4J_PASSWORD)
        )
        driver.verify_connectivity()
        logging.info(f"Connected to Neo4j at {NEO4J_URI}")
    except Exception as e:
        logging.error(f"Could not connect to Neo4j: {e}")
        sys.exit(1)

    logging.info("Flushing Neo4j database...")
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    def batch_upload(table_name, filename):
        data = parse_file(filename, table_name)
        if not data:
            return

        label = table_name.capitalize()
        cols = list(data[0].keys()) if data else []
        if not cols:
            return

        # Dynamically build UNWIND query
        # UNWIND $rows as row CREATE (n:Label {col1: row.col1, ...})
        props_str = ", ".join([f"`{c}`: row.`{c}`" for c in cols])
        query = f"""
        UNWIND $rows AS row
        CREATE (n:{label} {{ {props_str} }})
        """

        logging.info(f"Loading {table_name} ({len(data)} rows)...")

        batch_size = 2000
        total = 0

        with driver.session() as session:
            for i in range(0, len(data), batch_size):
                batch = data[i : i + batch_size]
                session.run(query, rows=batch)
                total += len(batch)

        logging.info(f"✅ Finished loading {total} nodes for {label}")

    # Load tables required for Query 8
    # NOTE: Neo4jConnector expects Capitalized labels (Region, Nation, etc.)
    batch_upload("region", "region.tbl")
    batch_upload("nation", "nation.tbl")
    batch_upload("part", "part.tbl")
    batch_upload("supplier", "supplier.tbl")
    batch_upload("customer", "customer.tbl")
    batch_upload("orders", "orders.tbl")
    batch_upload("lineitem", "lineitem.tbl")
    # batch_upload("partsupp", "partsupp.tbl")

    driver.close()


if __name__ == "__main__":
    repopulate_neo4j()
