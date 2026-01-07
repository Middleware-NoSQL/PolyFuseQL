import asyncio
import csv
import logging
import argparse
import time
import subprocess
import os
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

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logging.getLogger("py4j").setLevel(logging.WARNING)
logging.getLogger("pyspark").setLevel(logging.WARNING)

TPCH_DATA_DIR = "./docker/tpch-data"
RESULTS_FILE = "benchmark_unified_results.csv"

# Configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_PASSWORD = "tpch"

# Queries
QUERIES = {
    "Q1": """
          SELECT l_returnflag,
                 l_linestatus,
                 sum(l_quantity)                              as sum_qty,
                 sum(l_extendedprice)                         as sum_base_price,
                 sum(l_extendedprice * (1 - l_discount))      as sum_disc_price,
                 sum(l_extendedprice * (1 - l_discount) * (1 + l_tax))
                                                              as sum_charge,
                 avg(l_quantity)                              as avg_qty,
                 avg(l_extendedprice)                         as avg_price,
                 avg(l_discount)                              as avg_disc,
                 count(*)                                     as count_order
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
                 sum(case when nation = 'BRAZIL'
                              then volume else 0 end) /
                 sum(volume) as mkt_share
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
    "partsupp": [
        "ps_partkey",
        "ps_suppkey",
        "ps_availqty",
        "ps_supplycost",
        "ps_comment",
    ],
}


def get_hardware_info():
    try:
        info = {
            "cpu_physical": psutil.cpu_count(logical=False),
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "os": os.uname().sysname,
        }
        return info
    except:  # noqa:E722
        return {}


def parse_tbl_file(table_name, filepath):
    data = []
    columns = SCHEMAS[table_name]
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("|")
                row = {}
                for i, col in enumerate(columns):
                    if i >= len(parts):
                        break
                    val = parts[i]
                    try:
                        if "key" in col or "size" in col or "number" in col:
                            row[col] = int(val)
                        elif "price" in col or "bal" in col or "discount" in col:
                            row[col] = float(val)
                        else:
                            row[col] = val
                    except:  # noqa:E722
                        row[col] = val
                data.append(row)
    except Exception as e:
        logging.error(f"Error parsing {filepath}: {e}")
    return data


class UnifiedBenchmark:
    def __init__(self, scale_factor: float):
        self.scale_factor = scale_factor
        self.client = PolyClient()
        self.catalogue = Catalogue()
        self.hw_info = get_hardware_info()

    def generate_data(self):
        logging.info(f"--- Step 1: Generating Data (Scale: {self.scale_factor}) ---")
        abs_data_dir = os.path.abspath(TPCH_DATA_DIR)
        os.makedirs(abs_data_dir, exist_ok=True)

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
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            logging.info("Data generation successful.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Data generation failed: {e.stderr.decode()}")
            raise

    async def load_redis(self, data_type: str):
        logging.info(f"Loading Redis with strategy: {data_type.upper()}...")
        conn = RedisConnector(
            catalogue=self.catalogue, options={"data_type": data_type}
        )
        await conn.connect()
        logging.info("Flushing Redis...")
        await conn._client.flushall()

        tables = [
            "region",
            "nation",
            "part",
            "supplier",
            "customer",
            "orders",
            "lineitem",
        ]
        for table in tables:
            file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
            if not os.path.exists(file_path):
                continue
            logging.info(f"Loading {table} into Redis ({data_type})...")
            count = await conn.bulk_insert(table, file_path, batch_size=5000)
            logging.info(f"Loaded {count} rows for {table}")
        await conn.disconnect()

    async def load_neo4j(self):
        logging.info("Loading Neo4j...")
        conn = Neo4jConnector(catalogue=self.catalogue)
        await conn.connect()
        async with conn._driver.session() as s:
            await s.run("MATCH (n) DETACH DELETE n")

        tables = [
            "region",
            "nation",
            "part",
            "supplier",
            "customer",
            "orders",
            "lineitem",
        ]
        for table in tables:
            file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
            if not os.path.exists(file_path):
                continue
            logging.info(f"Loading {table} into Neo4j...")
            count = await conn.bulk_insert(table, file_path, batch_size=5000)
            logging.info(f"  > {table}: {count} nodes")
        await conn.disconnect()

    async def load_postgres(self):
        logging.info("Loading Postgres...")
        conn = PostgresConnector(catalogue=self.catalogue)
        await conn.connect()
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
            file_path = os.path.join(TPCH_DATA_DIR, f"{table}.tbl")
            if not os.path.exists(file_path):
                continue
            try:
                count = await conn.bulk_insert(table, file_path)
                logging.info(f"  > {table}: {count} rows")
            except Exception as e:
                logging.error(f"PG Load Error {table}: {e}")
        await conn.disconnect()

    async def execute_and_measure(
        self, engine: str, query_name: str, sql: str, options=None
    ):
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
                client_instance = PolyClient(options=options)
                try:
                    results = await client_instance.execute(sql, engine=engine)
                finally:
                    await client_instance.close_all_connections()

            duration = time.perf_counter() - start_time
            msg = f"Finished {query_name} on {engine} "
            msg += f"in {duration:.4f}s. Rows: {len(results)}"
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
            return {
                k.lower(): float(v) if isinstance(v, Decimal) else v
                for k, v in r.items()
            }

        t_norm = [norm(r) for r in truth]
        a_norm = [norm(r) for r in actual]

        t_norm.sort(key=lambda x: str(list(x.values())[0]))
        a_norm.sort(key=lambda x: str(list(x.values())[0]))

        match = True
        for t, a in zip(t_norm, a_norm):
            for k in t.keys():
                a_val = a.get(k) or a.get(k.replace("_", ""))
                if a_val is None:
                    match = False
                    continue
                t_val = t[k]
                if isinstance(t_val, (int, float)) and isinstance(a_val, (int, float)):
                    if abs(t_val - a_val) > 0.01:
                        match = False
                elif str(t_val) != str(a_val):
                    match = False
        return match

    async def run(self):
        self.generate_data()
        await self.load_postgres()

        scenarios = [
            {"target": "neo4j", "type": "native"},
            {"target": "redis", "type": "hash"},
            {"target": "redis", "type": "string"},
            {"target": "redis", "type": "json"},
        ]

        results_log = []

        for scen in scenarios:
            target = scen["target"]
            dtype = scen["type"]

            if target == "redis":
                await self.load_redis(dtype)
            elif target == "neo4j":
                await self.load_neo4j()

            for q_name, sql in QUERIES.items():
                logging.info(f"--- Benchmarking {q_name} | {target} ({dtype}) ---")
                gt_res, gt_time = await self.execute_and_measure(
                    "postgres_direct", q_name, sql
                )

                opts = {"data_type": dtype} if target == "redis" else None
                sut_res, sut_time = await self.execute_and_measure(
                    target, q_name, sql, options=opts
                )

                valid = self.compare_results(gt_res, sut_res)
                if valid:
                    logging.info(f"✅ {q_name} on {target} ({dtype}) PASSED.")
                else:
                    logging.error(f"❌ {q_name} on {target} ({dtype}) FAILED.")

                report = {
                    "scale": self.scale_factor,
                    "target": target,
                    "type": dtype,
                    "query": q_name,
                    "latency": sut_time,
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
                w = csv.DictWriter(f, fieldnames=keys)
                if not file_exists:
                    w.writeheader()
                w.writerows(results_log)
            logging.info(f"Benchmark finished. Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.01)
    args = parser.parse_args()
    asyncio.run(UnifiedBenchmark(args.scale).run())
