#!/bin/bash

# Generate TPC-H data
echo "Generating TPC-H data..."
docker-compose up -d dbgen

# Wait for the dbgen container to finish
docker wait tpch_dbgen

# Run the bulk loading script
echo "Running bulk load script..."
python3 scripts/bulk_load.py
