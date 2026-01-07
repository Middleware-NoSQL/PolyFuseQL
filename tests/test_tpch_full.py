import asyncio
import logging
import argparse
import time
import subprocess
import os
import csv
import psutil
import shutil
import sys
from decimal import Decimal
import asyncpg

from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.connector.Redis import RedisConnector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.catalogue.Catalogue import Catalogue

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
# Force logging to stdout and reset handlers to ensure INFO logs are visible
# regardless of what other libraries (like Spark) might have configured.
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# Reduce noise from 3rd party libs
logging.getLogger("py4j").setLevel(logging.WARNING)
logging.getLogger("pyspark").setLevel(logging.WARNING)

# -----------------------------------------------------------------------------
# Constants & Queries
# -----------------------------------------------------------------------------
TPCH_DATA_DIR = "./docker/tpch-data"
RESULTS_FILE = "benchmark_unified_results.csv"

# Queries
QUERIES = {
    "Q1": """
          SELECT l_returnflag,
                 l_linestatus,
                 sum(l_quantity)                                    as sum_qty,
                 sum(l_extendedprice)                        as sum_base_price,
                 sum(l_extendedprice * (1 - l_discount))        sum_disc_price,
                 sum(l_extendedprice * (1 - l_discount) * (1 + l_tax))
                                                                as sum_charge,
                 avg(l_quantity)                                     as avg_qty,
                 avg(l_extendedprice)                                as avg_price,
                 avg(l_discount)                                     as avg_disc,
                 count(*)                                            as count_order
          FROM lineitem
          WHERE l_shipdate <= date '1998-09-02'
          GROUP BY l_returnflag, l_linestatus
          ORDER BY l_returnflag, l_linestatus
          """,
    "Q6": """
          SELECT sum(l_extendedprice * l_discount) as revenue
          FROM lineitem
          WHERE l_shipdate >= date '1994-01-01'
            AND l_shipdate < date '1995-01-01'
            AND l_discount between 0.05 and 0.07
            AND l_quantity < 24
          """,
    "Q8": """
          SELECT o_year,
                 sum(case when nation = 'BRAZIL' then
                              volume else 0 end) / sum(volume) as mkt_share
          FROM (SELECT extract(year from o_orderdate)     as o_year,
                       l_extendedprice * (1 - l_discount) as volume,
                       n2.n_name                          as nation
                FROM part,
                     supplier,
                     lineitem,
                     orders,
                     customer,
                     nation n1,
                     nation n2,
                     region
                WHERE p_partkey = l_partkey
                  AND s_suppkey = l_suppkey
                  AND l_orderkey = o_orderkey
                  AND o_custkey = c_custkey
                  AND c_nationkey = n1.n_nationkey
                  AND n1.n_regionkey = r_regionkey
                  AND r_name = 'AMERICA'
                  AND s_nationkey = n2.n_nationkey
                  AND o_orderdate between date '1995-01-01' and date '1996-12-31'
                  AND p_type = 'ECONOMY ANODIZED STEEL') as all_nations
          GROUP BY o_year
          ORDER BY o_year
          """,
}


def get_hardware_info():
    try:
        info = {
            "cpu_physical": psutil.cpu_count(logical=False),
            "cpu_logical": psutil.cpu_count(logical=True),
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "os": os.uname().sysname,
        }
        return info
    except Exception:
        return {"info": "unavailable"}


class UnifiedBenchmark:
    def __init__(self, scale_factor: float):
        self.scale_factor = scale_factor
        self.client = PolyClient()
        self.catalogue = Catalogue()  # Load schema for connectors
        self.hw_info = get_hardware_info()

    def generate_data(self):
        """Generates TPC-H data locally."""
        logging.info(f"--- Step 1: Generating Data (Scale: {self.scale_factor}) ---")

        abs_data_dir = os.path.abspath(TPCH_DATA_DIR)
        os.makedirs(abs_data_dir, exist_ok=True)

        # Check for executable
        executable = shutil.which("tpchgen-cli")

        if executable:
            cmd = [
                executable,
                "--scale-factor",
                str(self.scale_factor),
                "--output-dir",
                abs_data_dir,
            ]
        else:
            # Fallback: Try running as a python module
            logging.info("'tpchgen-cli' not in PATH. Trying 'python -m tpchgen_cli'...")
            cmd = [
                sys.executable,
                "-m",
                "tpchgen_cli",
                "--scale-factor",
                str(self.scale_factor),
                "--output-dir",
                abs_data_dir,
            ]

        try:
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            logging.info("Data generation command executed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Data generation failed with exit code {e.returncode}.")
            logging.error(f"Stderr: {e.stderr.decode()}")
            raise
        except FileNotFoundError:
            msg = "Could not find 'tpchgen-cli' or python module. "
            msg += "Please install the data generator."
            logging.error(msg)
            raise

        # Verify files were created
        expected_tables = [
            "region",
            "nation",
            "part",
            "supplier",
            "customer",
            "orders",
            "lineitem",
            "partsupp",
        ]
        missing = []
        for tbl in expected_tables:
            fpath = os.path.join(abs_data_dir, f"{tbl}.tbl")
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                missing.append(tbl)

        if missing:
            logging.error(f"❌ Generation failed. Missing or empty tables: {missing}")
            raise RuntimeError("Data generation incomplete.")
        else:
            logging.info(
                f"✅ Verified {len(expected_tables)} .tbl files in {abs_data_dir}"
            )

    async def load_data(self, target: str):
        """Loads ALL required tables into the target backend."""
        logging.info(f"--- Step 2: Loading Data into {target.upper()} ---")

        tables = [
            "region",
            "nation",
            "part",
            "supplier",
            "customer",
            "orders",
            "lineitem",
            "partsupp",
        ]

        if target == "redis":
            conn = RedisConnector(catalogue=self.catalogue)
            await conn.connect()
            logging.info("Flushing Redis...")
            await conn._client.flushall()

            for table in tables:
                file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
                if not os.path.exists(file_path):
                    logging.warning(f"File {file_path} not found. Skipping.")
                    continue
                logging.info(f"Loading {table} into Redis...")
                count = await conn.bulk_insert(table, file_path)
                logging.info(f"Loaded {count} rows for {table}")
            await conn.disconnect()

        elif target == "neo4j":
            conn = Neo4jConnector(catalogue=self.catalogue)
            await conn.connect()
            logging.info("Flushing Neo4j...")
            async with conn._driver.session() as s:
                await s.run("MATCH (n) DETACH DELETE n")

            for table in tables:
                file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
                if not os.path.exists(file_path):
                    logging.warning(f"File {file_path} not found. Skipping.")
                    continue
                logging.info(f"Loading {table} into Neo4j...")
                count = await conn.bulk_insert(table, file_path, batch_size=5000)
                logging.info(f"Loaded {count} nodes for {table}")
            await conn.disconnect()

        elif target == "postgres":
            logging.info("Loading data into Postgres using bulk_insert...")
            conn = PostgresConnector(catalogue=self.catalogue)
            await conn.connect()

            ordered_tables = [
                "region",
                "nation",
                "part",
                "supplier",
                "partsupp",
                "customer",
                "orders",
                "lineitem",
            ]

            for table in ordered_tables:
                file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
                if not os.path.exists(file_path):
                    logging.warning(f"File {file_path} not found. Skipping.")
                    continue

                logging.info(f"Loading {table} into Postgres...")
                try:
                    count = await conn.bulk_insert(table, file_path)
                    logging.info(f"Loaded {count} rows for {table}")
                except Exception as e:
                    logging.error(f"Failed to load {table} into Postgres: {e}")

            await conn.disconnect()

    async def execute_and_measure(self, engine: str, query_name: str, sql: str):
        logging.info(f"Executing {query_name} on {engine}...")
        start_time = time.perf_counter()
        try:
            if engine == "postgres_direct":
                conn = await asyncpg.connect(
                    user="tpch",
                    password="tpch",
                    database="tpch",
                    host="localhost",
                    port=5432,
                )
                rows = await conn.fetch(sql)
                await conn.close()
                results = [dict(r) for r in rows]
            else:
                results = await self.client.execute(sql, engine=engine)

            duration = time.perf_counter() - start_time
            msg = f"Finished {query_name} on {engine} in {duration:.4f}s. "
            msg += f"Rows: {len(results)}"
            logging.info(msg)
            return results, duration
        except Exception as e:
            logging.error(f"Failed {query_name} on {engine}: {e}")
            return None, 0

    def compare_results(self, truth, actual):
        if truth is None or actual is None:
            return False
        if len(truth) != len(actual):
            logging.error(
                f"Row count mismatch: Truth={len(truth)}, Actual={len(actual)}"
            )
            return False

        def norm(r):
            # Normalize keys to lowercase and values to float for comparison
            return {
                k.lower(): float(v) if isinstance(v, Decimal) else v
                for k, v in r.items()
            }

        t_norm = [norm(r) for r in truth]
        a_norm = [norm(r) for r in actual]

        # Sort by the first value (usually year or grouping key)
        t_norm.sort(key=lambda x: str(list(x.values())[0]))
        a_norm.sort(key=lambda x: str(list(x.values())[0]))

        match = True
        for t, a in zip(t_norm, a_norm):
            for k in t.keys():
                # Handle potential key name differences (e.g. o_year vs oYear)
                a_val = a.get(k) or a.get(k.replace("_", ""))

                if a_val is None:
                    logging.error(f"Key {k} missing in actual result.")
                    match = False
                    continue

                t_val = t[k]
                if isinstance(t_val, (int, float)) and isinstance(a_val, (int, float)):
                    if abs(t_val - a_val) > 0.01:
                        logging.error(f"Value mismatch for {k}: {t_val} vs {a_val}")
                        match = False
                elif str(t_val) != str(a_val):
                    logging.error(f"Value mismatch for {k}: {t_val} vs {a_val}")
                    match = False
        return match

    async def run_benchmark(self):
        # 1. Generate Data
        self.generate_data()

        # 2. Load Data (Sequential)
        await self.load_data("postgres")

        backends = ["redis", "neo4j"]
        results_log = []

        for backend in backends:
            await self.load_data(backend)

            for q_name, sql in QUERIES.items():
                logging.info(f"--- Benchmarking {q_name} on {backend} ---")

                gt_res, gt_time = await self.execute_and_measure(
                    "postgres_direct", q_name, sql
                )
                sut_res, sut_time = await self.execute_and_measure(backend, q_name, sql)

                valid = self.compare_results(gt_res, sut_res)
                if valid:
                    logging.info(f"✅ {q_name} on {backend} PASSED.")
                else:
                    logging.error(f"❌ {q_name} on {backend} FAILED.")

                report = {
                    "scale": self.scale_factor,
                    "backend": backend,
                    "query": q_name,
                    "latency_s": sut_time,
                    "valid": valid,
                    "rows": len(sut_res) if sut_res else 0,
                    "ground_truth_latency_s": gt_time,
                    **self.hw_info,
                }
                results_log.append(report)

        if results_log:
            keys = results_log[0].keys()
            file_exists = os.path.isfile(RESULTS_FILE)
            with open(RESULTS_FILE, "a", newline="") as f:
                dict_writer = csv.DictWriter(f, fieldnames=keys)
                if not file_exists:
                    dict_writer.writeheader()
                dict_writer.writerows(results_log)
            logging.info(f"Benchmark finished. Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified PolyFuseQL Benchmark")
    parser.add_argument("--scale", type=float, default=0.01, help="TPC-H Scale Factor")
    args = parser.parse_args()

    bench = UnifiedBenchmark(args.scale)
    asyncio.run(bench.run_benchmark())
