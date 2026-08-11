#!/bin/bash

# Argument 1: Scale Factor (Default 0.01)
SCALE=${1:-0.01}

# Argument 2: Iterations (Default 30)
ITERATIONS=${2:-30}

# Argument 3: Start Step (Default 1)
START_STEP=${3:-1}

CHECKSUM_FILE=".postgres_state_${SCALE}.txt"

# Hostnames defined in your docker-compose.yml
HOST_POSTGRES="polyfuseql_pg_tpch"
HOST_REDIS="polyfuseql_redis_kv"
HOST_MONGO="polyfuseql_mongodb"
HOST_CASSANDRA="polyfuseql_cassandra"
HOST_NEO4J="polyfuseql_neo4j_graph"

# Helper: Wait for a specific TCP port to be open on the SERVICE_HOST
wait_for_port() {
    local HOST=$1
    local PORT=$2
    local SERVICE_NAME=$3
    echo "=========================================================="
    echo "🔍 WAITING FOR $SERVICE_NAME ($HOST:$PORT)..."
    echo "=========================================================="
    
    until nc -z "$HOST" "$PORT"; do
        echo "Service $SERVICE_NAME not reachable on $HOST:$PORT, retrying in 5s..."
        sleep 5
    done
    echo "✅ $SERVICE_NAME is ready."
    echo ""
}

# [ ... keep verify_integrity function as is ... ]

echo "=========================================================="
echo "STARTING SEQUENTIAL BENCHMARK SUITE (Docker-Network Mode)"
echo "=========================================================="
echo ""

# STEP 1: Postgres
if [ $START_STEP -le 1 ]; then
    wait_for_port $HOST_POSTGRES 5432 "POSTGRES"
    # Ensure your python script uses $HOST_POSTGRES as the host
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --target postgres --iterations $ITERATIONS
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --validate-only | grep "INTEGRITY_CHECKPOINT_DATA" | cut -d':' -f2 > "$CHECKSUM_FILE"
else
    verify_integrity
fi

# STEP 2: Redis
if [ $START_STEP -le 2 ]; then
    wait_for_port $HOST_REDIS 6379 "REDIS"
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --target redis --redis-type string --iterations $ITERATIONS --skip-load
    python tests/test_tpch_full.py --scale $SCALE --target redis --redis-type string --skip-load
fi

# STEP 3: MongoDB
if [ $START_STEP -le 3 ]; then
    wait_for_port $HOST_MONGO 27017 "MONGODB"
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --target mongodb --iterations $ITERATIONS --skip-load
    python tests/test_tpch_full.py --scale $SCALE --target mongodb --skip-load
fi

# STEP 4: Cassandra
if [ $START_STEP -le 4 ]; then
    wait_for_port $HOST_CASSANDRA 9042 "CASSANDRA"
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --target cassandra --iterations $ITERATIONS --skip-load
    python tests/test_tpch_full.py --scale $SCALE --target cassandra --skip-load
fi

# STEP 5: Neo4j
if [ $START_STEP -le 5 ]; then
    wait_for_port $HOST_NEO4J 7687 "NEO4J"
    python tests/test_tpch_oltp_full_v2.py --scale $SCALE --target neo4j --iterations $ITERATIONS --skip-load
    python tests/test_tpch_full.py --scale $SCALE --target neo4j --skip-load
fi
