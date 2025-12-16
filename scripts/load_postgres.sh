#!/bin/bash
set -e

# Configuration
DB_HOST=${POSTGRES_HOST:-postgres}
DB_USER=${POSTGRES_USER:-tpch}
DB_NAME=${POSTGRES_DB:-tpch}

# Ensure PGPASSWORD is set so psql can authenticate without prompt
export PGPASSWORD=${POSTGRES_PASSWORD}

echo "Waiting for Postgres at $DB_HOST..."
until pg_isready -h "$DB_HOST" -U "$DB_USER"; do
  sleep 2
done

echo "Postgres is up."

# -----------------------------------------------------------------------------
# 1. CLEANUP (Fixes duplicate key errors)
# -----------------------------------------------------------------------------
echo "🧹 Cleaning existing data to prevent duplicates..."
# We use CASCADE to automatically truncate dependent tables (e.g., truncating Region also clears Nation)
# We list all tables to be safe.
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "TRUNCATE lineitem, orders, customer, partsupp, supplier, part, nation, region RESTART IDENTITY CASCADE;"

# -----------------------------------------------------------------------------
# 2. BULK LOAD
# -----------------------------------------------------------------------------
echo "🚀 Starting Bulk Load..."

# List of tables to load in dependency order (referenced by Foreign Keys)
TABLES="region nation part supplier partsupp customer orders lineitem"

for table in $TABLES; do
    FILE="/data/$table.tbl"

    if [ -f "$FILE" ]; then
        echo "---------------------------------------------------"
        echo "Processing table: $table"
        echo "Source file: $FILE"

        # EXPLANATION OF FIX:
        # TPC-H .tbl files usually end with a '|', which Postgres sees as an extra column.
        # We use 'sed' to remove the trailing '|' from each line (s/|$//).
        # Then we pipe the clean output to psql using 'COPY FROM STDIN'.

        sed 's/|$//' "$FILE" | psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
            -c "COPY $table FROM STDIN WITH (FORMAT csv, DELIMITER '|');"

        echo "✅ $table loaded."
    else
        echo "⚠️  Warning: $FILE not found. Skipping."
    fi
done

echo "---------------------------------------------------"
echo "🎉 Postgres Bulk Load Complete."