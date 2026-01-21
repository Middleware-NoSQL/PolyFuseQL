import asyncio
import logging
import argparse
import time
import subprocess
import os
import random
import csv
import sys
import shutil
import psutil
import gc
import asyncpg
from typing import List, Dict, Any

from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.connector.Redis import RedisConnector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.MongoDb import MongoDbConnector
from polyfuseql.connector.Cassandra import CassandraConnector
from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings as app_settings

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
for lib in ["py4j", "pyspark", "cassandra", "neo4j", "aiohttp"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

TPCH_DATA_DIR = "./docker/tpch-data"
RESULTS_FILE = "benchmark_oltp_adapters_results.csv"


class OLTPBenchmarkAdapters:
    def __init__(self, scale_factor: float, target_db: str):
        self.scale_factor = scale_factor
        self.target_db = target_db.lower()
        self.client = PolyClient()
        self.catalogue = Catalogue()

        # Max keys approximation
        self.max_order_key = int(1_500_000 * scale_factor)
        self.max_cust_key = int(150_000 * scale_factor)
        self.max_order_key = max(1, self.max_order_key)
        self.max_cust_key = max(1, self.max_cust_key)

    def get_hw_info(self):
        return {
            "cpu": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "os": os.uname().sysname,
        }

    def generate_data(self):
        logging.info(f"--- Step 1: Generating Data (Scale: {self.scale_factor}) ---")
        abs_dir = os.path.abspath(TPCH_DATA_DIR)
        os.makedirs(abs_dir, exist_ok=True)

        exe = shutil.which("tpchgen-cli") or sys.executable
        cmd = [exe, "--scale-factor", str(self.scale_factor), "--output-dir", abs_dir]
        if exe == sys.executable:
            cmd.insert(1, "-m")
            cmd.insert(2, "tpchgen_cli")

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            logging.info("Data generation successful.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Data Gen Failed: {e.stderr.decode()}")
            if not os.listdir(abs_dir):
                raise

    async def load_database(self, backend: str):
        logging.info(f"--- Loading {backend.upper()} ---")

        # [FIX] Ordered list to satisfy Foreign Key constraints in Postgres
        # Region/Nation/Part/Supplier -> PartSupp -> Customer -> Orders -> LineItem
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

        connector = None
        if backend == "postgres":
            connector = PostgresConnector(self.catalogue)
        elif backend == "redis":
            connector = RedisConnector(self.catalogue, options={"data_type": "hash"})
        elif backend == "neo4j":
            connector = Neo4jConnector(self.catalogue)
        elif backend == "mongodb":
            connector = MongoDbConnector(
                settings=app_settings, catalogue=self.catalogue
            )
        elif backend == "cassandra":
            connector = CassandraConnector(
                settings=app_settings, catalogue=self.catalogue
            )

        if not connector:
            logging.error(f"No connector found for {backend}")
            return

        try:
            await connector.connect()
            for tbl in tables:
                fpath = os.path.join(TPCH_DATA_DIR, f"{tbl}.tbl")
                if not os.path.exists(fpath):
                    logging.warning(f"File not found: {fpath}")
                    continue

                logging.info(f"Loading {tbl} into {backend}...")
                count = await connector.bulk_insert(tbl, fpath)
                logging.info(f"Loaded {count} rows/ops.")
        except Exception as e:
            logging.error(f"Load failed for {backend}: {e}")
        finally:
            # [FIX] Ensure disconnect allows closing sessions properly
            await connector.disconnect()
            del connector
            gc.collect()

    async def run_query(self, backend, query_type, sql, iterations=10):
        latencies = []
        success = True

        for _ in range(iterations):
            start = time.perf_counter()
            try:
                # Force engine to target backend via PolyClient
                await self.client.execute(sql, engine=backend)
                latencies.append(time.perf_counter() - start)
            except Exception as e:
                logging.error(f"Query Failed ({backend} - {query_type}): {e}")
                success = False
                break

        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        return avg_lat, success

    async def run(self):
        self.generate_data()

        results = []
        logging.info("--- Starting OLTP Benchmark ---")

        # 1. Always load and benchmark Postgres first for Ground Truth validation
        if self.target_db != "postgres":
            await self.load_database("postgres")

        # Benchmarks definitions
        oid = random.randint(1, self.max_order_key)
        cid = random.randint(1, self.max_cust_key)
        benchmarks = [
            {
                "name": "Point Lookup (Order)",
                "sql": f"SELECT * FROM orders WHERE o_orderkey = {oid}",
            },
            {
                "name": "Point Lookup (Customer)",
                "sql": f"SELECT c_name, c_phone, c_acctbal FROM customer WHERE c_custkey = {cid}",
            },
            {
                "name": "Range Scan (LineItems)",
                "sql": f"SELECT * FROM lineitem WHERE l_orderkey = {oid}",
            },
            {
                "name": "Simple Filter (Status)",
                "sql": "SELECT o_orderkey, o_orderdate FROM orders WHERE o_orderstatus = 'F' LIMIT 20",
            },
            {
                "name": "Write (Insert)",
                "sql": f"INSERT INTO orders (o_orderkey, o_custkey, o_totalprice, o_orderdate) VALUES ({self.max_order_key + 999}, {cid}, 100.0, '2025-01-01')",
            },
        ]

        if self.target_db == "all":
            target_backends = ["postgres", "redis", "mongodb", "cassandra", "neo4j"]
        else:
            target_backends = [self.target_db]

        for backend in target_backends:
            await self.load_database(backend)

            for bench in benchmarks:
                logging.info(f"Benchmarking {backend}: {bench['name']}")

                if "Join" in bench["name"] and backend in ["mongodb", "cassandra"]:
                    pass

                latency, success = await self.run_query(
                    backend, bench["name"], bench["sql"]
                )

                results.append(
                    {
                        "backend": backend,
                        "query_type": bench["name"],
                        "latency_s": round(latency, 5),
                        "success": success,
                        "scale": self.scale_factor,
                        **self.get_hw_info(),
                    }
                )

            gc.collect()

        if results:
            keys = results[0].keys()
            file_exists = os.path.isfile(RESULTS_FILE)
            with open(RESULTS_FILE, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                if not file_exists:
                    w.writeheader()
                w.writerows(results)
            logging.info(f"Results saved to {RESULTS_FILE}")

        # Cleanup PolyClient sessions
        await self.client.close_all_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.01, help="TPC-H Scale Factor")
    parser.add_argument("--target", type=str, default="all", help="Target DB")
    args = parser.parse_args()

    b = OLTPBenchmarkAdapters(args.scale, args.target)
    asyncio.run(b.run())
