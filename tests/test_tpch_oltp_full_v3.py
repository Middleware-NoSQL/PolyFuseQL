import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'src')))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'tests')))

import asyncio
import logging
import argparse
import time
import subprocess
import random
import csv
import shutil
import psutil
import gc
import asyncpg
import traceback
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.connector.Redis import RedisConnector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.MongoDb import MongoDbConnector
from polyfuseql.connector.Cassandra import CassandraConnector
from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings as app_settings

try:
    import load_cassandra_v2 as cassandra_tpch_loader
except ImportError:
    cassandra_tpch_loader = None

load_dotenv()

def enforce_docker_host(env_var, default_docker_name):
    """Prevents 'localhost' errors by forcing internal docker names in JupyterHub"""
    val = os.getenv(env_var, default_docker_name)
    if val in ["localhost", "127.0.0.1", "0.0.0.0"]:
        val = default_docker_name
    os.environ[env_var] = val
    return val

HOST_POSTGRES = enforce_docker_host("POSTGRES_HOST", "polyfuseql-pg-tpch")
HOST_REDIS = enforce_docker_host("REDIS_HOST", "polyfuseql-redis-kv")
HOST_MONGO = enforce_docker_host("MONGODB_HOST", "polyfuseql-mongodb")
HOST_NEO4J = enforce_docker_host("NEO4J_HOST", "polyfuseql-neo4j-graph")
HOST_CASSANDRA = enforce_docker_host("CASSANDRA_HOST", "polyfuseql-cassandra")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
for lib in ["py4j", "pyspark", "cassandra", "neo4j", "aiohttp"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

TPCH_DATA_DIR = "./docker/tpch-data"
RESULTS_FILE = "benchmark_oltp_v2_metrics.csv"

class ResourceMonitor:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.process = psutil.Process()
        self.peak_ram_mb = 0.0
        self.avg_cpu_percent = 0.0
        self._running = False
        self._monitor_task = None

    async def _sample_memory(self):
        while self._running:
            try:
                mem = self.process.memory_info().rss / (1024 * 1024)
                if mem > self.peak_ram_mb:
                    self.peak_ram_mb = mem
            except Exception:
                pass
            await asyncio.sleep(self.interval)

    async def __aenter__(self):
        self._running = True
        self.process.cpu_percent()
        self.peak_ram_mb = self.process.memory_info().rss / (1024 * 1024)
        self._monitor_task = asyncio.create_task(self._sample_memory())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self.avg_cpu_percent = self.process.cpu_percent()

class OLTPBenchmarkAdapters:
    def __init__(self, scale_factor: float, target_db: str, iterations: int, skip_load: bool, redis_type: str, validate_only: bool):
        self.scale_factor = scale_factor
        self.target_db = target_db.lower()
        self.iterations = iterations
        self.skip_load = skip_load
        self.redis_type = redis_type
        self.validate_only = validate_only
        
        client_options = {"data_type": redis_type} if target_db == "redis" else None
        self.client = PolyClient(options=client_options)
        self.catalogue = Catalogue()

        self.max_order_key = max(1, int(6_000_000 * scale_factor))
        self.max_cust_key = max(1, int(150_000 * scale_factor))

    def get_hw_info(self):
        try:
            return {
                "cpu": psutil.cpu_count(),
                "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
                "os": os.uname().sysname,
            }
        except:
            return {}

    def generate_data(self):
        if self.skip_load: return
        logging.info(f"--- Step 1: Generating Data (Scale: {self.scale_factor}) ---")
        abs_dir = os.path.abspath(TPCH_DATA_DIR)
        os.makedirs(abs_dir, exist_ok=True)
        exe = shutil.which("tpchgen-cli") or sys.executable
        cmd = [exe, "--scale-factor", str(self.scale_factor), "--output-dir", abs_dir]
        if exe == sys.executable:
            cmd.insert(1, "-m")
            cmd.insert(2, "tpchgen_cli")
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logging.error(f"Data Gen Failed: {e.stderr.decode()}")

    async def load_database(self, backend: str, results_list: Optional[List[Dict]] = None):
        if self.skip_load: return
        logging.info(f"--- Loading {backend.upper()} ---")
        load_success, cpu_usage, ram_usage, duration = True, 0.0, 0.0, 0.0
        error_msg = ""

        try:
            async with ResourceMonitor() as monitor:
                start_time = time.perf_counter()
                
                if backend == "cassandra" and cassandra_tpch_loader:
                    cassandra_tpch_loader.run_load(
                        keyspace="mykeyspace", data_dir=TPCH_DATA_DIR,
                        hosts=[HOST_CASSANDRA], port=9042,
                        user=os.getenv("CASSANDRA_USER", "cassandra"), password=os.getenv("CASSANDRA_PASSWORD", "cassandra")
                    )
                else:
                    tables = ["region", "nation", "part", "supplier", "partsupp", "customer", "orders", "lineitem"]
                    connector = None
                    if backend == "postgres": connector = PostgresConnector(self.catalogue)
                    elif backend == "redis": connector = RedisConnector(self.catalogue, options={"data_type": self.redis_type})
                    elif backend == "neo4j": connector = Neo4jConnector(self.catalogue)
                    elif backend == "mongodb": connector = MongoDbConnector(settings=app_settings, catalogue=self.catalogue)
                    elif backend == "cassandra": connector = CassandraConnector(settings=app_settings, catalogue=self.catalogue)

                    if connector:
                        await connector.connect()
                        if backend == "redis": await connector._client.flushall()
                        for tbl in tables:
                            fpath = os.path.join(TPCH_DATA_DIR, f"{tbl}.tbl")
                            if os.path.exists(fpath):
                                await connector.bulk_insert(tbl, fpath)
                        await connector.disconnect()
                duration = time.perf_counter() - start_time
            cpu_usage = monitor.avg_cpu_percent
            ram_usage = monitor.peak_ram_mb
        except Exception as e:
            load_success, error_msg = False, str(e)
            logging.error(f"Load failed for {backend}: {e}")

        if results_list is not None:
            results_list.append({
                "backend": backend, "query_type": "Bulk Load", "latency_s": round(duration, 5),
                "success": load_success, "validation_passed": True,
                "cpu_usage": cpu_usage, "ram_usage_mb": ram_usage,
                "scale": self.scale_factor, "error": error_msg, **self.get_hw_info(),
            })

    async def perform_validation(self):
        try:
            conn = await asyncpg.connect(
                user=os.getenv("POSTGRES_USER", "tpch"), password=os.getenv("POSTGRES_PASSWORD", "tpch"),
                database=os.getenv("POSTGRES_DB", "tpch"), host=HOST_POSTGRES, port=os.getenv("POSTGRES_PORT", "5432")
            )
            results = {}
            for tbl in ["orders", "lineitem", "customer"]:
                rows = await conn.fetch(f"SELECT count(*) as cnt FROM {tbl}")
                results[tbl] = rows[0]['cnt']
            await conn.close()
            print(f">>> INTEGRITY_CHECKPOINT_DATA:" + ",".join([f"{k}={v}" for k, v in results.items()]))
        except Exception as e:
            print(f">>> INTEGRITY_CHECKPOINT_DATA:ERROR:{e}")
            sys.exit(1)

    async def run_query(self, backend, query_type, sql):
        latencies, success = [], True
        async with ResourceMonitor() as monitor:
            for i in range(self.iterations):
                start = time.perf_counter()
                current_sql = sql.replace("__ITER__", str(i))
                try:
                    await self.client.execute(current_sql, engine=backend)
                    latencies.append(time.perf_counter() - start)
                except Exception as e:
                    logging.warning(f"Query Failed ({sql}) ({backend}): {e}")
                    success = False
                    break
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        return avg_lat, success, monitor.avg_cpu_percent, monitor.peak_ram_mb

    async def run(self):
        if self.validate_only:
            await self.perform_validation()
            return

        self.generate_data()
        results = []
        
        if self.target_db == "postgres": await self.load_database("postgres", results)

        oid = random.randint(1, self.max_order_key)
        cid = random.randint(1, self.max_cust_key)
        insert_key = int(self.max_order_key + 9999 + random.randint(1, 100000))

        benchmarks = [
            {"name": "Point Lookup (Order)", "sql": f"SELECT * FROM orders WHERE o_orderkey = {int(oid)}"},
            {"name": "Point Lookup (Customer)", "sql": f"SELECT c_name, c_phone, c_acctbal FROM customer WHERE c_custkey = {int(cid)}"},
            {"name": "Range Scan (LineItems)", "sql": f"SELECT * FROM lineitem WHERE l_orderkey = {int(oid)}"},
            {"name": "Simple Filter (Status)", "sql": "SELECT o_orderkey, o_orderdate FROM orders WHERE o_orderstatus = 'F' AND o_orderkey > 0 LIMIT 20"},
            {"name": "Write (Insert)", "sql": f"INSERT INTO orders (o_orderkey, o_custkey, o_orderstatus, o_totalprice, o_orderdate, o_orderpriority, o_clerk, o_shippriority, o_comment) VALUES ({insert_key}00__ITER__, {int(cid)}, 'F', 100.0, '2025-01-01', '5-LOW', 'Clerk#000000951', 0, 'No Comment')"},
        ]

        targets = ["postgres", "redis", "mongodb", "cassandra", "neo4j"] if self.target_db == "all" else [self.target_db]

        for backend in targets:
            await self.load_database(backend, results)
            for bench in benchmarks:
                try:
                    lat, succ, cpu, ram = await self.run_query(backend, bench["name"], bench["sql"])
                    results.append({
                        "backend": backend, "query_type": bench["name"], "latency_s": round(lat, 5),
                        "success": succ, "validation_passed": succ, "cpu_usage": cpu, "ram_usage_mb": ram,
                        "scale": self.scale_factor, **self.get_hw_info(),
                    })
                except Exception as e:
                    results.append({"backend": backend, "query_type": bench["name"], "success": False, "error": str(e), "scale": self.scale_factor})
            gc.collect()

        if results:
            keys = results[0].keys()
            file_exists = os.path.isfile(RESULTS_FILE)
            with open(RESULTS_FILE, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                if not file_exists: w.writeheader()
                w.writerows(results)
            logging.info(f"Results saved to {RESULTS_FILE}")

        await self.client.close_all_connections()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.01)
    parser.add_argument("--target", type=str, default="all")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--skip-load", action="store_true")
    parser.add_argument("--redis-type", type=str, default="hash")
    parser.add_argument("--validate-only", action="store_true")
    # Accept any other random args without crashing
    args, unknown = parser.parse_known_args()

    b = OLTPBenchmarkAdapters(args.scale, args.target, args.iterations, args.skip_load, args.redis_type, args.validate_only)
    asyncio.run(b.run())
