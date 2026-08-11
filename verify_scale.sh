#!/bin/bash

# Default to scale factor 10 if no argument is provided
SF=${1:-10}

# Calculate expected using Python to handle floats like 0.01 easily
ORDERS_EXPECTED=$(python3 -c "print(f'{int(1500000 * float(\"$SF\")):,}')")
REGION_EXPECTED="5"

echo "============================================================"
echo "TPC-H Scale Factor $SF Verification via Docker"
echo "Expected 'orders' count: ~$ORDERS_EXPECTED"
echo "Expected 'region' count: $REGION_EXPECTED"
echo "============================================================"

# Source .env if it exists to get credentials, though we hardcode defaults fallback
if [ -f ".env" ]; then
    source .env
fi

PG_USER=${POSTGRES_USER:-tpch}
PG_PASS=${POSTGRES_PASSWORD:-tpch}
PG_DB=${POSTGRES_DB:-tpch}

MONGO_USER=${MONGODB_USER:-root}
MONGO_PASS=${MONGODB_PASSWORD:-example}

REDIS_PASS=${REDIS_PASSWORD:-tpch}

NEO_USER=${NEO4J_USER:-neo4j}
NEO_PASS=${NEO4J_PASSWORD:-password}

# 1. POSTGRES
echo -e "\n🐘 Checking POSTGRES..."
docker exec -e PGPASSWORD="$PG_PASS" polyfuseql-pg-tpch psql -U "$PG_USER" -d "$PG_DB" -t -c "SELECT count(*) FROM orders;" | xargs

# 2. MONGODB
echo -e "\n🍃 Checking MONGODB..."
docker exec polyfuseql-mongodb mongosh "$PG_DB" -u "$MONGO_USER" -p "$MONGO_PASS" --authenticationDatabase admin --quiet --eval "db.orders.countDocuments()"

# 3. NEO4J
echo -e "\n🕸️  Checking NEO4J..."
docker exec polyfuseql-neo4j-graph cypher-shell -u "$NEO_USER" -p "$NEO_PASS" "MATCH (n:Order) RETURN count(n);" | tail -n 1

# 4. CASSANDRA
echo -e "\n👁️  Checking CASSANDRA..."
echo "Cassandra 'region' count (should be 5):"
docker exec polyfuseql-cassandra cqlsh -e "SELECT count(*) FROM tpch.region;" | grep -A 2 "count" | tail -n 1 | xargs
echo "Cassandra 'orders' estimated partitions (approx orders):"
docker exec polyfuseql-cassandra nodetool tablestats tpch.orders | grep "Number of partitions (estimate)"

# 5. REDIS
echo -e "\n🔴 Checking REDIS..."
echo "Redis Total Keys (DBSIZE):"
docker exec polyfuseql-redis-kv redis-cli -a "$REDIS_PASS" --no-auth-warning DBSIZE

echo -e "\n============================================================"
echo "Verification Complete!"

