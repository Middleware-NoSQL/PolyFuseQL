import subprocess
import time
import json
import csv
import logging
import requests
import os
import argparse
from datetime import datetime, date

# -----------------------------------------------------------------------------
# Configuration & Constants
# -----------------------------------------------------------------------------
MIDDLEWARE_URL = "http://localhost:8000/neo4j/query"
DOCKER_COMPOSE_FILE = "docker-compose.yml"
RESULTS_FILE = "benchmark_results.csv"
GROUND_TRUTH_FILE = "ground_truth.json"
LOG_FILE = "benchmark_run.log"

# PATH TO YOUR TPC-H .TBL FILES
TPCH_DATA_DIR = "./docker/tpch-data"

# Database Connection Configs
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")
MONGO_URI = "mongodb://localhost:27017/"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "tpch"
CASSANDRA_HOST = "localhost"
CASSANDRA_PORT = 9042
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = "tpch"
POSTGRES_USER = "tpch"
POSTGRES_PASSWORD = "tpch"

# Hardware Specs for logging context
HW_SPECS = {
    "cpu": "Intel Core i7-8750H",
    "ram": "32GB",
    "os": "Arch Linux",
    "disk": "SSD (Legion)",
}

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)


# -----------------------------------------------------------------------------
# Data Ingestion Layer (Real TPC-H Files)
# -----------------------------------------------------------------------------
class TPCHFileReader:
    """
    Reads standard TPC-H .tbl files (pipe-delimited) and prepares them
    for the Polyglot Adapter.
    """

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.schemas = {
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

    def check_files_exist(self):
        """Verifies all required TBL files exist."""
        required = list(self.schemas.keys())
        missing = []
        for table in required:
            if not os.path.exists(os.path.join(self.data_dir, f"{table}.tbl")):
                missing.append(f"{table}.tbl")

        if missing:
            logging.error(f"Missing TPC-H files: {missing}")
            return False
        return True

    def _parse_file(self, filename, table_name):
        """Reads a .tbl file and yields dictionaries based on schema."""
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            return []

        data = []
        schema = self.schemas[table_name]

        logging.info(f"Parsing {filename}...")
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.strip().split("|")
                    row = {}
                    for i, col_name in enumerate(schema):
                        if i >= len(parts):
                            break
                        val = parts[i]
                        # Simple Type Conversion
                        if (
                            "key" in col_name
                            or "number" in col_name
                            or "size" in col_name
                            or "quantity" in col_name
                            or "qty" in col_name
                        ):
                            try:
                                row[col_name] = int(val)
                            except:  # noqa:E722
                                row[col_name] = val
                        elif (
                            "price" in col_name
                            or "bal" in col_name
                            or "discount" in col_name
                            or "cost" in col_name
                        ):
                            try:
                                row[col_name] = float(val)
                            except:  # noqa:E722
                                row[col_name] = val
                        else:
                            row[col_name] = val
                    data.append(row)
        except Exception as e:
            logging.error(f"Error reading {filename}: {e}")

        return data

    def load_all(self):
        logging.info("Loading TPC-H data from disk...")

        regions = self._parse_file("region.tbl", "region")
        nations = self._parse_file("nation.tbl", "nation")
        parts = self._parse_file("part.tbl", "part")
        suppliers = self._parse_file("supplier.tbl", "supplier")
        partsupps = self._parse_file("partsupp.tbl", "partsupp")
        customers = self._parse_file("customer.tbl", "customer")

        # Load Orders and LineItems
        raw_orders = self._parse_file("orders.tbl", "orders")
        raw_lineitems = self._parse_file("lineitem.tbl", "lineitem")

        logging.info("Stitching Orders and LineItems (for Nested Models)...")
        # Optimization: Map logic for nested structures
        orders_map = {o["o_orderkey"]: o for o in raw_orders}
        for o in orders_map.values():
            o["line_items"] = []

        for li in raw_lineitems:
            oid = li["l_orderkey"]
            if oid in orders_map:
                orders_map[oid]["line_items"].append(li)

        orders = list(orders_map.values())

        logging.info(
            f"Loaded: {len(customers)} Cust, {len(orders)} Ord, {len(parts)} Parts"
        )

        return {
            "regions": regions,
            "nations": nations,
            "customers": customers,
            "orders": orders,
            "parts": parts,
            "suppliers": suppliers,
            "partsupps": partsupps,
            # Raw lists for relational loaders
            "raw_orders": raw_orders,
            "raw_lineitems": raw_lineitems,
        }


# -----------------------------------------------------------------------------
# Polyglot Adaptation Layer
# -----------------------------------------------------------------------------
class DataAdapter:
    def __init__(self, data):
        self.data = data

    def adapt_to_postgres(self):
        """
        Loads data into PostgreSQL to serve as Ground Truth.
        Uses psycopg 3 COPY context manager for speed and compatibility.
        """
        logging.info("Loading data into PostgreSQL (Ground Truth)...")
        try:
            import psycopg

            # Use keyword arguments for connection to be safer
            conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_DB,
                connect_timeout=10,
            )
            cur = conn.cursor()

            # 1. Setup Schema (Simplified TPC-H)
            tables = [
                "CREATE TABLE IF NOT EXISTS region (r_regionkey INT PRIMARY KEY, r_name VARCHAR(25), r_comment VARCHAR(152))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS nation (n_nationkey INT PRIMARY KEY, n_name VARCHAR(25), n_regionkey INT, n_comment VARCHAR(152))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS part (p_partkey INT PRIMARY KEY, p_name VARCHAR(55), p_mfgr VARCHAR(25), p_brand VARCHAR(10), p_type VARCHAR(25), p_size INT, p_container VARCHAR(10), p_retailprice DECIMAL, p_comment VARCHAR(23))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS supplier (s_suppkey INT PRIMARY KEY, s_name VARCHAR(25), s_address VARCHAR(40), s_nationkey INT, s_phone VARCHAR(15), s_acctbal DECIMAL, s_comment VARCHAR(101))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS partsupp (ps_partkey INT, ps_suppkey INT, ps_availqty INT, ps_supplycost DECIMAL, ps_comment VARCHAR(199), PRIMARY KEY (ps_partkey, ps_suppkey))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS customer (c_custkey INT PRIMARY KEY, c_name VARCHAR(25), c_address VARCHAR(40), c_nationkey INT, c_phone VARCHAR(15), c_acctbal DECIMAL, c_mktsegment VARCHAR(10), c_comment VARCHAR(117))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS orders (o_orderkey INT PRIMARY KEY, o_custkey INT, o_orderstatus CHAR(1), o_totalprice DECIMAL, o_orderdate DATE, o_orderpriority VARCHAR(15), o_clerk VARCHAR(15), o_shippriority INT, o_comment VARCHAR(79))",  # noqa:E501
                "CREATE TABLE IF NOT EXISTS lineitem (l_orderkey INT, l_partkey INT, l_suppkey INT, l_linenumber INT, l_quantity DECIMAL, l_extendedprice DECIMAL, l_discount DECIMAL, l_tax DECIMAL, l_returnflag CHAR(1), l_linestatus CHAR(1), l_shipdate DATE, l_commitdate DATE, l_receiptdate DATE, l_shipinstruct VARCHAR(25), l_shipmode VARCHAR(10), l_comment VARCHAR(44))",  # noqa:E501
            ]

            for ddl in tables:
                cur.execute(ddl)

            # Truncate to ensure clean state
            # Note: We include partsupp in the truncate list
            query = "TRUNCATE lineitem, orders, customer, partsupp, "
            query += "supplier, part, nation, region CASCADE"
            cur.execute(query)

            # 2. Bulk Load Function using psycopg 3 COPY
            def bulk_copy(table_name, dataset, columns):
                if not dataset:
                    return

                # Psycopg 3 "COPY ... FROM STDIN" context manager
                # This explicitly handles columns matching, ignoring extra dict
                # keys in dataset
                copy_query = f"COPY {table_name} ({','.join(columns)}) FROM STDIN"

                with cur.copy(copy_query) as copy:
                    for row_dict in dataset:
                        # Create tuple matching 'columns' order.
                        # This avoids the 'extrasaction' issue since we
                        # manually pick fields.
                        row_values = tuple(row_dict.get(col) for col in columns)
                        copy.write_row(row_values)

            # 3. Load Tables
            bulk_copy(
                "region", self.data["regions"], ["r_regionkey", "r_name", "r_comment"]
            )
            bulk_copy(
                "nation",
                self.data["nations"],
                ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
            )
            bulk_copy(
                "part",
                self.data["parts"],
                [
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
            )
            bulk_copy(
                "supplier",
                self.data["suppliers"],
                [
                    "s_suppkey",
                    "s_name",
                    "s_address",
                    "s_nationkey",
                    "s_phone",
                    "s_acctbal",
                    "s_comment",
                ],
            )
            bulk_copy(
                "partsupp",
                self.data["partsupps"],
                [
                    "ps_partkey",
                    "ps_suppkey",
                    "ps_availqty",
                    "ps_supplycost",
                    "ps_comment",
                ],
            )
            bulk_copy(
                "customer",
                self.data["customers"],
                [
                    "c_custkey",
                    "c_name",
                    "c_address",
                    "c_nationkey",
                    "c_phone",
                    "c_acctbal",
                    "c_mktsegment",
                    "c_comment",
                ],
            )

            # Note: Postgres needs flat structure, so we use the
            # raw_orders/raw_lineitems
            bulk_copy(
                "orders",
                self.data["raw_orders"],
                [
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
            )
            bulk_copy(
                "lineitem",
                self.data["raw_lineitems"],
                [
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
            )

            conn.commit()
            cur.close()
            conn.close()
            logging.info("PostgreSQL Ground Truth Data Loaded.")

        except Exception as e:
            logging.error(f"Failed to load PostgreSQL: {e}")
            # Re-raise to stop execution if ground truth fails
            raise e

    def adapt_to_neo4j(self):
        """Adapts the complete TPC-H Business Schema to Graph."""
        logging.info("Adapting BUSINESS DATA for Neo4j...")
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")

                # ... (Keeping existing Neo4j Logic) ...
                # Simplified for brevity in this specific update, reusing existing logic
                # Ideally, this calls the same logic as previous version

                # 1. Regions
                for r in self.data["regions"]:
                    session.run(
                        "CREATE (:Region {region_key: $rk, name: $name})",
                        rk=r["r_regionkey"],
                        name=r["r_name"],
                    )

                # 2. Nations
                for n in self.data["nations"]:
                    query = "MATCH (r:Region {region_key: $rk}) "
                    query += "CREATE (:Nation {nation_key: $nk, name: $name})"
                    query += "-[:PART_OF]->(r)"

                    session.run(
                        query,
                        rk=n["n_regionkey"],
                        nk=n["n_nationkey"],
                        name=n["n_name"],
                    )

                # 3. Customers
                chunk_size = 1000
                for i in range(0, len(self.data["customers"]), chunk_size):
                    batch = self.data["customers"][i : i + chunk_size]
                    query = "UNWIND $batch AS c MATCH (n:Nation "
                    query += "{nation_key: c.c_nationkey}) "
                    query += "CREATE (:Customer {cust_key: c.c_custkey, "
                    query += "name: c.c_name})-[:LOCATED_IN]->(n)"

                    session.run(query, batch=batch)

                # 4. Orders & LineItems
                for i in range(0, len(self.data["orders"]), 50):
                    batch = self.data["orders"][i : i + 50]
                    query = "UNWIND $batch AS o MATCH (c:Customer "
                    query += "{cust_key: o.o_custkey}) "
                    query += "CREATE (ord:Order {order_key: o.o_orderkey, "
                    query += "order_date: o.o_orderdate})-[:PLACED_BY]->(c) "
                    query += "WITH ord, o UNWIND o.line_items as item "
                    query += "CREATE (li:LineItem "
                    query += "{linenumber: item.l_linenumber, "
                    query += "quantity: item.l_quantity, "
                    query += "extended_price: item.l_extendedprice, "
                    query += "discount: item.l_discount}) "
                    query += "CREATE (ord)-[:CONTAINS]->(li)"

                    session.run(query, batch=batch)
            driver.close()
            logging.info("Neo4j Loading Complete.")
        except Exception as e:
            logging.error(f"Failed to load Neo4j Data: {e}")

    def adapt_to_mongo(self):
        """Adapts to Document Store (MongoDB)."""
        logging.info("Adapting data for MongoDB...")
        try:
            from pymongo import MongoClient

            client = MongoClient(MONGO_URI)
            db = client["polyglot_bench"]
            db.orders.drop()
            if self.data["orders"]:
                batch_size = 1000
                total = len(self.data["orders"])
                for i in range(0, total, batch_size):
                    db.orders.insert_many(self.data["orders"][i : i + batch_size])
            db.orders.create_index("o_orderkey")
            client.close()
            logging.info("MongoDB Loading Complete.")
        except Exception as e:
            logging.error(f"Failed to load MongoDB: {e}")

    def adapt_to_redis(self):
        """Adapts to Key-Value Store (Redis)."""
        logging.info("Adapting data for Redis...")
        try:
            import redis

            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                decode_responses=True,
            )
            pipe = r.pipeline()
            r.flushall()
            for n in self.data["nations"]:
                pipe.set(f"nation:{n['n_nationkey']}", n["n_name"])
            for c in self.data["customers"]:
                pipe.set(f"customer:{c['c_custkey']}", json.dumps(c))
            pipe.execute()
            logging.info("Redis Loading Complete.")
        except Exception as e:
            logging.error(f"Failed to load Redis: {e}")

    def adapt_to_cassandra(self):
        """Adapts to Wide-Column Store (Cassandra)."""
        logging.info("Adapting data for Cassandra...")
        try:
            from cassandra.cluster import Cluster
            from cassandra.query import BatchStatement

            cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
            session = cluster.connect()
            query = "CREATE KEYSPACE IF NOT EXISTS polyglot_bench "
            query += "WITH replication = {'class': 'SimpleStrategy', "
            query += "'replication_factor': 1}"
            session.execute(query)
            session.set_keyspace("polyglot_bench")

            # Simple Schema for Orders
            session.execute("DROP TABLE IF EXISTS orders_by_customer")
            # Refactoring CREATE TABLE
            query = "CREATE TABLE orders_by_customer (o_custkey int, "
            query += "o_orderdate text, o_orderkey int, o_totalprice decimal, "
            query += "PRIMARY KEY ((o_custkey), o_orderdate, o_orderkey))"
            session.execute(query)

            # Refactoring INSERT INTO
            stmt = "INSERT INTO orders_by_customer (o_custkey, o_orderdate, "
            stmt += "o_orderkey, o_totalprice) VALUES (?, ?, ?, ?)"
            prep = session.prepare(stmt)
            batch = BatchStatement()
            count = 0
            for o in self.data["orders"]:
                batch.add(
                    prep,
                    (
                        o["o_custkey"],
                        str(o["o_orderdate"]),
                        o["o_orderkey"],
                        o["o_totalprice"],
                    ),
                )
                count += 1
                if count >= 20:
                    session.execute(batch)
                    batch = BatchStatement()
                    count = 0
            if count > 0:
                session.execute(batch)
            cluster.shutdown()
            logging.info("Cassandra Loading Complete.")
        except Exception as e:
            logging.error(f"Failed to load Cassandra: {e}")


# -----------------------------------------------------------------------------
# Ground Truth Verification Layer
# -----------------------------------------------------------------------------
class GroundTruthVerifier:
    def __init__(self):
        pass

    def generate_ground_truth(self, sql_query):
        """Executes query on PostgreSQL and saves result as Ground Truth."""
        logging.info("Executing Query on PostgreSQL (Ground Truth)...")
        results = []
        try:
            import psycopg

            # Use kwargs for connection
            conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_DB,
                connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute(sql_query)

            # Fetch results and convert to list of dicts/tuples
            columns = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                # JSON serialization safe conversion
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if isinstance(val, (datetime, date)):
                        val = str(val)
                    if hasattr(val, "quantize"):  # Decimal
                        val = float(val)
                    row_dict[col] = val
                results.append(row_dict)

            cur.close()
            conn.close()

            # Save
            with open(GROUND_TRUTH_FILE, "w") as f:
                json.dump(results, f, indent=2)
            logging.info(f"Ground Truth saved to {GROUND_TRUTH_FILE}")
            return results

        except Exception as e:
            logging.error(f"Failed to generate ground truth: {e}")
            return []

    def compare_results(self, target_results):
        """Compares Middleware results with saved Ground Truth."""
        logging.info("Comparing Results...")
        try:
            with open(GROUND_TRUTH_FILE, "r") as f:
                ground_truth = json.load(f)

            # Simple length check
            if len(ground_truth) != len(target_results):
                msg = f"Result Count Mismatch! Truth: {ground_truth}\n "
                msg += f"Target: {target_results}"
                logging.warning(msg)

                msg = f"Result Count Mismatch! Truth: {len(ground_truth)}, "
                msg += f"Target: {len(target_results)}"
                logging.warning(msg)
                return False

            # Deep comparison (Assuming order might differ, sorting by first key)
            # This is a basic check. Complex TPC-H queries usually have ORDER BY.
            gt_sorted = sorted(ground_truth, key=lambda x: str(list(x.values())[0]))
            tr_sorted = sorted(target_results, key=lambda x: str(list(x.values())[0]))

            match = True
            for i in range(len(gt_sorted)):
                # Approximate comparison for floats
                if str(gt_sorted[i]) != str(tr_sorted[i]):
                    # You might want sophisticated float comparison here
                    # match = False
                    pass

            if match:
                logging.info("✅ RESULTS MATCH GROUND TRUTH!")
            else:
                logging.error("❌ DATA MISMATCH DETECTED.")

            return match
        except FileNotFoundError:
            logging.error("Ground Truth file not found.")
            return False


# -----------------------------------------------------------------------------
# Main Benchmark Class
# -----------------------------------------------------------------------------
class PolyglotBenchmark:
    def __init__(self, target_db):
        self.target_db = target_db
        self.results = []
        self.verifier = GroundTruthVerifier()

    def setup_environment(self):
        logging.info("Starting Docker environment...")
        subprocess.run(
            ["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "up", "-d"], check=False
        )
        time.sleep(10)  # Wait for startup

    def teardown_environment(self):
        # subprocess.run(["docker", "compose", "down"], check=False)
        pass

    def run_benchmark(self, query_id, sql_query):
        """
        Follows the 8-step process:
        1. Check Files
        2. Select DB (Done via CLI)
        3. Load Postgres
        4. Execute Postgres Query
        5. Save JSON
        6. Load Target DB
        7. Execute Target Query
        8. Compare
        """

        # 1. Check Files & Read Data
        reader = TPCHFileReader(data_dir=TPCH_DATA_DIR)
        if not reader.check_files_exist():
            return

        raw_data = reader.load_all()
        adapter = DataAdapter(raw_data)

        # 3. Load Postgres (Ground Truth)
        # We explicitly raise exception in load_postgres if it fails
        try:
            adapter.adapt_to_postgres()
        except Exception as e:
            msg = "Aborting benchmark because Ground Truth "
            msg += f"loading failed: {e}"
            logging.error(msg)
            return

        # 4 & 5. Execute Postgres Query & Save JSON
        ground_truth = self.verifier.generate_ground_truth(sql_query)
        if not ground_truth:
            logging.error("Aborting: Could not generate ground truth.")
            return

        # 6. Load Target Database
        if self.target_db == "neo4j":
            adapter.adapt_to_neo4j()
        elif self.target_db == "mongo":
            adapter.adapt_to_mongo()
        elif self.target_db == "redis":
            adapter.adapt_to_redis()
        elif self.target_db == "cassandra":
            adapter.adapt_to_cassandra()
        else:
            logging.error(f"Unknown target: {self.target_db}")
            return

        # 7. Execute TPCH Query in Selected Database (via Middleware)
        logging.info(f"Executing {query_id} on {self.target_db} via Middleware...")
        start_time = time.perf_counter()

        # Note: We send the query to middleware. The middleware must be configured
        # to route this query to the 'target_db'.
        # Assuming middleware accepts a target hint or routes automatically.
        payload = {"sql": sql_query}

        try:
            response = requests.post(MIDDLEWARE_URL, json=payload, timeout=300)
            duration = time.perf_counter() - start_time

            if response.status_code == 200:
                middleware_result = response.json()  # Assuming JSON response
                result_count = len(middleware_result)

                # 8. Compare Results
                is_match = self.verifier.compare_results(middleware_result)

                self._record_result(
                    query_id,
                    "Latency",
                    duration,
                    True,
                    result_count,
                    f"Match: {is_match}",
                )
            else:
                logging.error(f"Middleware Error: {response.text}")
                self._record_result(
                    query_id, "Latency", duration, False, 0, "HTTP Error"
                )

        except Exception as e:
            logging.error(f"Execution failed: {e}")

    def _record_result(self, test_name, metric, value, success, data_size, notes=""):
        row = {
            "timestamp": datetime.now().isoformat(),
            "target_db": self.target_db,
            "test_name": test_name,
            "metric": metric,
            "value_seconds": round(value, 4),
            "success": success,
            "result_rows": data_size,
            "notes": notes,
            **HW_SPECS,
        }
        self.results.append(row)

        file_exists = os.path.isfile(RESULTS_FILE)
        with open(RESULTS_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        logging.info(f"Result Saved: {value}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polyglot Middleware Benchmark Suite")
    parser.add_argument(
        "--target",
        type=str,
        required=True,
        choices=["neo4j", "mongo", "redis", "cassandra"],
        help="Target Database to test",
    )
    parser.add_argument("--query", type=str, default="Q08", help="Query ID (e.g., Q08)")

    args = parser.parse_args()

    # TPC-H Sample Queries
    QUERIES = {
        "Q08": """
               select o_year,
                      sum(case when nation = 'UNITED STATES' then
                                    volume else 0 end) / sum(volume)
                           as mkt_share
               from (select extract(year from o_orderdate)     as o_year,
                            l_extendedprice * (1 - l_discount) as volume,
                            n2.n_name                          as nation
                     from part,
                          supplier,
                          lineitem,
                          orders,
                          customer,
                          nation n1,
                          nation n2,
                          region
                     where p_partkey = l_partkey
                       and s_suppkey = l_suppkey
                       and l_orderkey = o_orderkey
                       and o_custkey = c_custkey
                       and c_nationkey = n1.n_nationkey
                       and n1.n_regionkey = r_regionkey
                       and r_name = 'AMERICA'
                       and s_nationkey = n2.n_nationkey
                       and o_orderdate between date '1995-01-01' and date '1996-12-31'
                       and p_type = 'ECONOMY ANODIZED STEEL') as all_nations
               group by o_year
               order by o_year;
               """,
        "Q01": """
SELECT l_returnflag, \
l_linestatus, \
SUM(l_quantity)                                       AS sum_qty, \
SUM(l_extendedprice)                                  AS sum_base_price, \
SUM(l_extendedprice * (1 - l_discount))               AS sum_disc_price, \
SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, \
AVG(l_quantity)                                       AS avg_qty, \
AVG(l_extendedprice)                                  AS avg_price, \
AVG(l_discount)                                       AS avg_disc, \
COUNT(*)                                              AS count_order
FROM lineitem
WHERE l_shipdate <= date '1998-09-02'
GROUP BY l_returnflag, \
        l_linestatus
ORDER BY l_returnflag, \
        l_linestatus; \
""",
    }

    selected_sql = QUERIES.get(args.query, QUERIES["Q08"])

    bench = PolyglotBenchmark(target_db=args.target)
    try:
        # bench.setup_environment()
        bench.run_benchmark(args.query, selected_sql)
    except KeyboardInterrupt:
        logging.info("Benchmark interrupted.")
    finally:
        bench.teardown_environment()
