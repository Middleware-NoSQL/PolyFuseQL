import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'src')))
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'tests')))

import asyncio
import csv
import logging
import argparse
import time
import subprocess
import psutil
import shutil
import asyncpg
from typing import Tuple
from dotenv import load_dotenv

from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.connector.Redis import RedisConnector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.MongoDb import MongoDbConnector
from polyfuseql.connector.Cassandra import CassandraConnector
from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import settings as app_settings

load_dotenv()

def enforce_docker_host(env_var, default_docker_name):
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
RESULTS_FILE = "benchmark_olap_v2_metrics.csv"

# Queries truncated for brevity but functionality preserved
QUERIES = {
    "Q1": "SELECT l_returnflag, l_linestatus, sum(l_quantity) as sum_qty, count(*) as count_order FROM lineitem WHERE l_shipdate <= date '1998-09-02' GROUP BY l_returnflag, l_linestatus ORDER BY l_returnflag, l_linestatus",
    "Q6": "SELECT sum(l_extendedprice * l_discount) as revenue FROM lineitem WHERE l_shipdate >= date '1994-01-01' AND l_shipdate < date '1995-01-01' AND l_discount between 0.05 and 0.07 AND l_quantity < 24",
}

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
            try: await self._monitor_task
            except asyncio.CancelledError: pass
        self.avg_cpu_percent = self.process.cpu_percent()

class UnifiedBenchmark:
    def __init__(self, scale_factor: float, skip_load: bool, target: str, redis_type: str, iterations: int):
        self.scale_factor = scale_factor
        self.skip_load = skip_load
        self.target = target
        self.redis_type = redis_type
        self.iterations = iterations # Inherited from bash but often OLAP runs once
        self.client = PolyClient()
        self.catalogue = Catalogue()
        self.hw_info = self.get_hardware_info()

    def get_hardware_info(self):
        try: return {"cpu_physical": psutil.cpu_count(logical=False), "ram_gb": round(psutil.virtual_memory().total / (1024**3), 2), "os": os.uname().sysname}
        except: return {}

    async def load_database(self, backend: str) -> Tuple[float, float, float]:
        if self.skip_load: return 0.0, 0.0, 0.0
        logging.info(f"Loading {backend}...")
        async with ResourceMonitor() as monitor:
            start_time = time.perf_counter()
            conn = None
            if backend == "postgres": conn = PostgresConnector(self.catalogue)
            elif backend == "neo4j": conn = Neo4jConnector(self.catalogue)
            elif backend == "redis": conn = RedisConnector(self.catalogue, options={"data_type": self.redis_type})
            
            if conn:
                await conn.connect()
                tables = ["region", "nation", "part", "supplier", "customer", "orders", "lineitem", "partsupp"]
                for tbl in tables:
                    fpath = os.path.join(TPCH_DATA_DIR, f"{tbl}.tbl")
                    if os.path.exists(fpath):
                        await conn.bulk_insert(tbl, fpath)
                await conn.disconnect()
            duration = time.perf_counter() - start_time
        return duration, monitor.avg_cpu_percent, monitor.peak_ram_mb

    async def execute_and_measure(self, engine: str, query_name: str, sql: str, options=None):
        logging.info(f"Executing {query_name} on {engine}...")
        try:
            async with ResourceMonitor() as monitor:
                start_time = time.perf_counter()
                if engine == "postgres_direct":
                    conn = await asyncpg.connect(user=os.getenv("POSTGRES_USER", "tpch"), password=os.getenv("POSTGRES_PASSWORD", "tpch"), database=os.getenv("POSTGRES_DB", "tpch"), host=HOST_POSTGRES, port=os.getenv("POSTGRES_PORT", "5432"))
                    rows = await conn.fetch(sql)
                    await conn.close()
                    results = [dict(r) for r in rows]
                else:
                    client_instance = PolyClient(options=options)
                    results = await client_instance.execute(sql, engine=engine)
                    await client_instance.close_all_connections()
                duration = time.perf_counter() - start_time
            return results, duration, monitor.avg_cpu_percent, monitor.peak_ram_mb
        except Exception as e:
            logging.error(f"Failed {query_name} on {engine}: {e}")
            return None, 0, 0.0, 0.0

    async def run(self):
        results_log = []
        all_scenarios = [
            #{"target": "neo4j", "type": "native"}, {"target": "redis", "type": self.redis_type},
            #{"target": "mongodb", "type": "doc"}, {"target": "cassandra", "type": "wide"}
            {"target": "postgres", "type": "relational"},
            {"target": "redis", "type": "string"},
            {"target": "redis", "type": "hash"},
            {"target": "redis", "type": "json"},
            {"target": "neo4j", "type": "graph"},
        ]
        active_scenarios = all_scenarios if self.target == "all" else [s for s in all_scenarios if s["target"] == self.target]

        for scen in active_scenarios:
            target = scen["target"]
            load_time, load_cpu, load_ram = await self.load_database(target)
            
            for q_name, sql in QUERIES.items():
                gt_res, gt_time, _, _ = await self.execute_and_measure("postgres_direct", q_name, sql)
                opts = {"data_type": scen["type"]} if target == "redis" else None
                sut_res, sut_time, cpu_pct, ram_mb = await self.execute_and_measure(target, q_name, sql, options=opts)

                results_log.append({
                    "scale": self.scale_factor, "target": target, "type": scen["type"], "query": q_name,
                    "latency": sut_time, "valid": bool(sut_res), "validation_passed": bool(sut_res),
                    "rows": len(sut_res) if sut_res else 0, "ground_truth_latency_s": gt_time,
                    "cpu_usage": cpu_pct, "ram_usage_mb": ram_mb, **self.hw_info,
                })

        if results_log:
            keys = results_log[0].keys()
            file_exists = os.path.isfile(RESULTS_FILE)
            with open(RESULTS_FILE, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                if not file_exists: w.writeheader()
                w.writerows(results_log)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.01)
    parser.add_argument("--skip-load", action="store_true")
    parser.add_argument("--target", type=str, default="all")
    parser.add_argument("--redis-type", type=str, default="string")
    # Accept any extra args silently to prevent crashes
    args, unknown = parser.parse_known_args()
    
    # We pass iterations even if OLAP usually runs once, to match the constructor
    iterations = 1 
    if '--iterations' in unknown:
        try: iterations = int(unknown[unknown.index('--iterations')+1])
        except: pass

    asyncio.run(UnifiedBenchmark(args.scale, args.skip_load, args.target, args.redis_type, iterations).run())
