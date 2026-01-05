import pytest
import logging
import asyncpg
from decimal import Decimal
from polyfuseql.client.PolyClient import PolyClient
from scripts.load_redis_v2 import repopulate_redis

# TPC-H Query 8 (National Market Share)
TPCH_QUERY_8 = """
               select o_year,
                      sum(case when nation = 'UNITED STATES'
                                   then volume else 0 end) / sum(volume)
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
               order by o_year; \
               """


def normalize_row(row):
    """
    Normalizes dictionary keys (camelCase -> snake_case) and values (Decimal -> float)
    for loose comparison between different backend drivers.
    """
    new_row = {}
    for k, v in row.items():
        # Key normalization: oYear -> o_year
        k_lower = k.lower()
        key_map = {"oyear": "o_year", "mktshare": "mkt_share"}
        clean_key = key_map.get(k_lower, k_lower)

        # Value normalization
        if isinstance(v, Decimal):
            clean_val = float(v)
        else:
            clean_val = v

        new_row[clean_key] = clean_val
    return new_row


@pytest.fixture(scope="module")
def setup_redis_data():
    """
    Fixture that runs once per module.
    It parses the TPC-H files and loads them into Redis
    to ensure the database is not empty and has correct JSON format.
    """
    logging.info("FIXTURE: Repopulating Redis with TPC-H data...")
    try:
        repopulate_redis()
        logging.info("FIXTURE: Redis Population Complete.")
    except Exception as e:
        pytest.fail(f"Failed to populate Redis: {e}")


@pytest.mark.asyncio
async def test_tpch_query8_comparison(setup_redis_data):
    """
    Executes TPC-H Query 8 against Postgres (Ground Truth) and Redis
    (System Under Test),
    then compares the results.
    """
    client = PolyClient()

    # -------------------------------------------------------------------------
    # 1. Execute on Postgres (Ground Truth)
    # -------------------------------------------------------------------------
    logging.info(
        "Executing Q8 on Postgres (Ground Truth) using direct asyncpg connection..."
    )
    postgres_results = []
    try:
        # Connect to Postgres directly using standard TPC-H credentials
        # Adjust credentials if your local environment differs
        conn = await asyncpg.connect(
            user="tpch", password="tpch", database="tpch", host="localhost", port=5432
        )

        # asyncpg returns a list of Record objects
        rows = await conn.fetch(TPCH_QUERY_8)
        await conn.close()

        # Convert Records to standard dicts for comparison
        postgres_results = [dict(row) for row in rows]

    except Exception as e:
        msg = "Failed to execute query on Postgres directly. Ensure Postgres "
        msg += "is running on localhost:5432 with user/db 'tpch'. "
        msg += f"Error: {e}"
        pytest.fail(msg)

    msg = f"Postgres Results ({len(postgres_results)} rows): "
    msg += f"{postgres_results}"
    logging.info(msg)

    if not postgres_results:
        msg = "Postgres returned empty results! "
        msg += "Verify TPC-H data is loaded in Postgres."
        logging.warning(msg)

    # -------------------------------------------------------------------------
    # 2. Execute on Redis (PolyFuseQL + Spark)
    # -------------------------------------------------------------------------
    logging.info("Executing Q8 on Redis...")
    redis_results = await client.execute(TPCH_QUERY_8, engine="redis")

    logging.info(f"Redis Results ({len(redis_results)} rows): {redis_results}")

    # -------------------------------------------------------------------------
    # 3. Compare Results
    # -------------------------------------------------------------------------

    # Normalize results for comparison
    pg_norm = [normalize_row(r) for r in postgres_results]
    rd_norm = [normalize_row(r) for r in redis_results]

    # Sort by year to ensure alignment
    pg_norm.sort(key=lambda x: x.get("o_year", 0))
    rd_norm.sort(key=lambda x: x.get("o_year", 0))

    print("\n--- COMPARISON ---")
    print(f"Postgres (Normalized): {pg_norm}")
    print(f"Redis    (Normalized): {rd_norm}")

    assert len(rd_norm) == len(
        pg_norm
    ), f"Row count mismatch! Postgres: {len(pg_norm)}, Redis: {len(rd_norm)}"

    for pg_row, rd_row in zip(pg_norm, rd_norm):
        assert (
            pg_row["o_year"] == rd_row["o_year"]
        ), f"Year mismatch: {pg_row['o_year']} != {rd_row['o_year']}"

        # Compare market share with tolerance
        pg_share = pg_row["mkt_share"]
        rd_share = rd_row["mkt_share"]

        # Check if values are reasonably close (float precision issues)
        msg = f"Market Share mismatch for {pg_row['o_year']}: "
        msg += f"Postgres={pg_share}, Redis={rd_share}"
        assert abs(pg_share - rd_share) < 0.001, msg

    logging.info("✅ Redis results match Postgres ground truth!")
