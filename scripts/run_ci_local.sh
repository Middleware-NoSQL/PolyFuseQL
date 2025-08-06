#!/usr/bin/env bash
# scripts/run_ci_local.sh
# This script replicates the CI workflow on your local machine.

# Exit immediately if a command exits with a non-zero status.
set -e

# --- 1. Clean up previous runs ---
echo "🧹 Cleaning up old containers and volumes..."
docker-compose down -v

# --- 2. Start the full stack ---
echo "🚀 Starting the Docker Compose stack in the background..."
docker-compose up --build -d

# --- 3. Wait for all services to be healthy ---
echo "⏳ Waiting for all services to pass their health checks..."
./scripts/wait-for-services.sh

# --- 4. Install dependencies ---
echo "🐍 Installing Python dependencies with Poetry..."
poetry install --with dev

# --- 5. Run tests ---
echo "🧪 Running tests with pytest..."
poetry run pytest -q --cov=polyfuseql --cov-report=xml

echo "✅ CI simulation finished successfully!"