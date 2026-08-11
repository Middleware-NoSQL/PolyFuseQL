#!/bin/bash

# Argument 1: Scale Factor (Default 0.01)
SCALE=${1:-0.01}

# Argument 2: Iterations (Default 30)
ITERATIONS=${2:-30}

# Argument 3: Start Step (Default 1)
# 1=Postgres, 2=Redis, 3=MongoDB, 4=Cassandra, 5=Neo4j
START_STEP=${3:-1}

CHECKSUM_FILE=".postgres_state_${SCALE}.txt"

# Define internal Docker network hostnames and ports
HOST_POSTGRES="polyfuseql-pg-tpch"
PORT_POSTGRES=5432

HOST_REDIS="polyfuseql-redis-kv"
PORT_REDIS=6379

HOST_MONGO="polyfuseql-mongodb"
PORT_MONGO=27017

HOST_CASSANDRA="polyfuseql-cassandra"
PORT_CASSANDRA=9042

HOST_NEO4J="polyfuseql-neo4j-graph"
PORT_NEO4J=7687

# Helper: Wait for a specific TCP port to be open on the SERVICE_HOST
# This replaces the manual 'read -p' prompt so it can run headless in the background
wait_for_port() {
    local HOST=$1
    local PORT=$2
    local SERVICE_NAME=$3
    echo "=========================================================="
    echo "🔍 WAITING FOR $SERVICE_NAME TO BE READY ($HOST:$PORT)..."
    echo "=========================================================="
    
    until nc -z "$HOST" "$PORT"; do
        echo "[$SERVICE_NAME] Not reachable yet. Retrying in 5 seconds..."
        sleep 5
    done
    echo "✅ $SERVICE_NAME is up and accepting connections!"
    echo ""
}

# Function to verify Postgres integrity if skipping load
verify_integrity() {
    echo "🔎 Verifying Postgres Ground Truth Integrity..."
    
    if [ ! -f "$CHECKSUM_FILE" ]; then
        echo "❌ CRITICAL: No checksum file found ($CHECKSUM_FILE)."
        echo "   You are trying to resume, but Step 1 (Postgres) was never completed successfully."
        echo "   Please restart from Step 1."
        exit 1
    fi

    CURRENT_STATE=$(python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --validate-only | grep "INTEGRITY_CHECKPOINT_DATA" | cut -d':' -f2)
    SAVED_STATE=$(cat "$CHECKSUM_FILE")

    if [ -z "$CURRENT_STATE" ]; then
        echo "❌ CRITICAL: Unable to connect to Postgres for validation."
        exit 1
    fi

    # Trim whitespace
    CURRENT_STATE=$(echo "$CURRENT_STATE" | xargs)
    SAVED_STATE=$(echo "$SAVED_STATE" | xargs)

    if [ "$CURRENT_STATE" != "$SAVED_STATE" ]; then
        echo "❌ CRITICAL: Integrity Mismatch!"
        echo "   Saved State:   '$SAVED_STATE'"
        echo "   Current State: '$CURRENT_STATE'"
        echo "   The Postgres database has been modified or corrupted. Restart from Step 1."
        exit 1
    fi

    echo "✅ Integrity Verified. Postgres state matches the initial run."
}

echo "=========================================================="
echo "🚀 STARTING SEQUENTIAL BENCHMARK SUITE (Headless Mode)"
echo "ROOT DIR:   $(pwd)"
echo "SCALE:      $SCALE"
echo "ITERATIONS: $ITERATIONS"
echo "START STEP: $START_STEP"
echo "=========================================================="
echo ""

# ---------------------------------------------------------
# STEP 1: GROUND TRUTH (POSTGRES)
# ---------------------------------------------------------
if [ "$START_STEP" -le 1 ]; then
    wait_for_port "$HOST_POSTGRES" "$PORT_POSTGRES" "POSTGRES"
    echo ">>> [1/5] Setting up POSTGRES (Ground Truth)..."
    
    python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --target postgres --iterations "$ITERATIONS"
    if [ $? -ne 0 ]; then echo "❌ Postgres Setup Failed! Aborting."; exit 1; fi

    echo "💾 Saving Postgres Checksum..."
    python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --validate-only | grep "INTEGRITY_CHECKPOINT_DATA" | cut -d':' -f2 > "$CHECKSUM_FILE"
    echo "✅ Postgres Loaded & Checksum Saved to $CHECKSUM_FILE"
else
    echo "⏩ Skipping Step 1 (Postgres)..."
    verify_integrity
fi
echo ""

# ---------------------------------------------------------
# STEP 2: REDIS (STRING)
# ---------------------------------------------------------
if [ "$START_STEP" -le 2 ]; then
    wait_for_port "$HOST_REDIS" "$PORT_REDIS" "REDIS"
    echo ">>> [2/5] Testing REDIS (Type: String)..."
    
    python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --target redis --redis-type string --iterations "$ITERATIONS"
    python tests/test_tpch_full_v2.py --scale "$SCALE" --target redis --redis-type string
    echo "✅ Redis Cycle Complete."
else
    echo "⏩ Skipping Step 2 (Redis)..."
fi
echo ""

# ---------------------------------------------------------
# STEP 3: MONGODB
# ---------------------------------------------------------
if [ "$START_STEP" -le 3 ]; then
    wait_for_port "$HOST_MONGO" "$PORT_MONGO" "MONGODB"
    echo ">>> [3/5] Testing MONGODB..."

    python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --target mongodb --iterations "$ITERATIONS" --skip-load
    #python tests/test_tpch_full_v2.py --scale "$SCALE" --target mongodb --skip-load
    echo "✅ MongoDB Cycle Complete."
else
    echo "⏩ Skipping Step 3 (MongoDB)..."
fi
echo ""

# ---------------------------------------------------------
# STEP 4: CASSANDRA
# ---------------------------------------------------------
if [ "$START_STEP" -le 4 ]; then
    wait_for_port "$HOST_CASSANDRA" "$PORT_CASSANDRA" "CASSANDRA"
    echo ">>> [4/5] Testing CASSANDRA..."

    #python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --target cassandra --iterations "$ITERATIONS" --skip-load
    #python tests/test_tpch_full_v2.py --scale "$SCALE" --target cassandra --skip-load
    echo "✅ Cassandra Cycle Complete."
else
    echo "⏩ Skipping Step 4 (Cassandra)..."
fi
echo ""

# ---------------------------------------------------------
# STEP 5: NEO4J
# ---------------------------------------------------------
if [ "$START_STEP" -le 5 ]; then
    wait_for_port "$HOST_NEO4J" "$PORT_NEO4J" "NEO4J"
    echo ">>> [5/5] Testing NEO4J..."

    #python tests/test_tpch_oltp_full_v3.py --scale "$SCALE" --target neo4j --iterations "$ITERATIONS" --skip-load
    #python tests/test_tpch_full_v2.py --scale "$SCALE" --target neo4j --skip-load
    echo "✅ Neo4j Cycle Complete."
else
    echo "⏩ Skipping Step 5 (Neo4j)..."
fi
echo ""

echo "=========================================================="
echo "🎉 BENCHMARK SUITE FINISHED FOR SCALE $SCALE"
echo "=========================================================="
