#!/usr/bin/env bash
# scripts/wait-for-services.sh

# This script waits for all essential services in docker-compose to be "healthy"
# before allowing the CI pipeline to proceed.

set -e

# --- Check for jq dependency ---
if ! command -v jq &> /dev/null
then
    echo "❌ Error: jq is not installed. Please install it to continue."
    echo "On Arch Linux, run: sudo pacman -S jq"
    exit 1
fi

TIMEOUT=180  # 3 minutes
INTERVAL=5   # Check every 5 seconds
ELAPSED=0

echo "Waiting for services to become healthy..."

while true; do
  # Use `docker compose ps --format json` to get reliable status info.
  # The `-s` flag tells jq to "slurp" all JSON objects from the stream into a single array.
  # This is the key fix that makes the command robust.
  unhealthy_count=$(docker compose ps --format json | jq -s 'map(select(.State != "running (healthy)")) | length')

  if [ "$unhealthy_count" -eq 0 ]; then
    echo "✅ All services are healthy."
    break
  fi

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "❌ Timeout: Services did not become healthy within ${TIMEOUT} seconds."
    docker compose logs # Dump logs for debugging
    exit 1
  fi

  echo "... ${unhealthy_count} service(s) not healthy yet. Waiting ${INTERVAL}s..."
  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

exit 0
