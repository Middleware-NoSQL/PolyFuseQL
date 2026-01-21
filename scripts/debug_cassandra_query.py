import asyncio
import logging
import sys
import time
from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
from cassandra.auth import PlainTextAuthProvider
from cassandra import ConsistencyLevel
from cassandra.query import SimpleStatement
from cassandra.policies import WhiteListRoundRobinPolicy
from polyfuseql.client.PolyClient import PolyClient

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# Specific query causing issues
# [FIX] Middleware expects pure SQL. Do NOT add ALLOW FILTERING here for middleware.
TARGET_QUERY_SQL = "SELECT * FROM lineitem WHERE l_orderkey = 196001"

# For direct CQL, we might need it depending on schema, but usually PK lookups don't.
# We will inspect schema to decide.
TARGET_KEY = 196001


async def debug_query_middleware():
    client = PolyClient()

    logging.info(f"--- [Middleware] Starting Debug for Query: {TARGET_QUERY_SQL} ---")
    logging.info(f"Target Backend: Cassandra (via Middleware)")

    try:
        start_time = time.perf_counter()

        # Force execution on Cassandra
        results = await client.execute(TARGET_QUERY_SQL, engine="cassandra")

        end_time = time.perf_counter()
        latency = end_time - start_time

        logging.info(f"--- [Middleware] Query Successful ---")
        logging.info(f"Latency: {latency:.4f} seconds")

        if isinstance(results, list):
            logging.info(f"Rows returned: {len(results)}")
            if len(results) > 0:
                logging.info(f"First row sample: {results[0]}")
        else:
            logging.info(f"Result type: {type(results)}")

    except Exception as e:
        logging.error(f"--- [Middleware] Query Failed ---")
        logging.error(f"Error Type: {type(e).__name__}")
        logging.error(f"Error Message: {e}")
        if hasattr(e, "response"):
            try:
                text = await e.response.text()
                logging.error(f"Response Status: {e.response.status}")
                logging.error(f"Response Body: {text}")
            except:
                pass

    finally:
        await client.close_all_connections()
        logging.info("--- [Middleware] Debug Session Finished ---")


def debug_query_direct():
    logging.info(f"--- [Direct] Starting Debug ---")

    # Direct Connection Config
    hosts = ["127.0.0.1"]  # Explicit IPv4
    port = 9043
    user = "cassandra"
    password = "cassandra"
    keyspace = "mykeyspace"

    cluster = None
    try:
        auth_provider = PlainTextAuthProvider(username=user, password=password)

        # [FIX] Define execution profile with relaxed consistency and high timeout
        profile = ExecutionProfile(
            request_timeout=60.0,  # 60 seconds timeout
            consistency_level=ConsistencyLevel.LOCAL_ONE,
        )

        cluster = Cluster(
            contact_points=hosts,
            port=port,
            auth_provider=auth_provider,
            protocol_version=4,
            # Force protocol v4 to avoid negotiation issues
            execution_profiles={EXEC_PROFILE_DEFAULT: profile},
        )
        session = cluster.connect()

        logging.info(f"Connected to Cassandra at {hosts}:{port}")

        # Verify Keyspace
        row = session.execute(
            "SELECT keyspace_name FROM system_schema.keyspaces WHERE keyspace_name = %s",
            [keyspace],
        ).one()
        if not row:
            logging.error(f"Keyspace '{keyspace}' does not exist!")
            return

        session.set_keyspace(keyspace)
        logging.info(f"Using keyspace: {keyspace}")

        # Verify Schema / Partition Key
        table_meta = cluster.metadata.keyspaces[keyspace].tables.get("lineitem")
        if table_meta:
            pk_names = [c.name for c in table_meta.partition_key]
            logging.info(f"Table 'lineitem' found. Partition Key: {pk_names}")

            # Construct CQL based on schema
            # [FIX] Explicitly added ALLOW FILTERING because the previous error code 2200 demanded it.
            # Even if l_orderkey is PK, if the driver/server thinks filtering is needed, we must provide it.
            cql_query = "SELECT * FROM lineitem WHERE l_orderkey = %s ALLOW FILTERING"
        else:
            logging.error("Table 'lineitem' not found in metadata!")
            return

        logging.info(f"Executing Direct CQL: {cql_query} with value {TARGET_KEY}")

        start_time = time.perf_counter()
        # Pass parameters properly to avoid injection/formatting issues
        rows = session.execute(cql_query, [TARGET_KEY])
        end_time = time.perf_counter()

        results = list(rows)
        latency = end_time - start_time

        logging.info(f"--- [Direct] Query Successful ---")
        logging.info(f"Latency: {latency:.4f} seconds")
        logging.info(f"Rows returned: {len(results)}")
        if len(results) > 0:
            logging.info(f"First row sample: {results[0]}")
        else:
            logging.info("No rows found for this ID.")

    except Exception as e:
        logging.error(f"--- [Direct] Query Failed ---")
        logging.error(f"Error Type: {type(e).__name__}")
        logging.error(f"Error Message: {e}")

    finally:
        if cluster:
            cluster.shutdown()
        logging.info("--- [Direct] Debug Session Finished ---")


async def main():
    # Run Direct Test First (to verify DB health)
    debug_query_direct()

    print("\n" + "=" * 50 + "\n")

    # Run Middleware Test
    await debug_query_middleware()


if __name__ == "__main__":
    asyncio.run(main())
