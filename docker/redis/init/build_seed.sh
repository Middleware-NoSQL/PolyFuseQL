#!/usr/bin/env sh
# docker/redis/init/build_seed.sh
set -euo pipefail

err(){ printf >&2 "❌  %s\n" "$*"; exit 1; }

# ensure jq is available
command -v jq >/dev/null 2>&1 || err "jq not installed"

JSON=${1:-/seed/northwind.json}
SEED=${2:-/seed/seed.redis}

[ -f "$JSON" ] || err "JSON file not found: $JSON"

echo "🔎  Root keys: $(jq -r 'keys[]' "$JSON" | paste -sd',' -)" >&2

# Clear out old seed
: > "$SEED"

# For each table name
jq -r 'keys[]' "$JSON" | while read -r table; do
  # Iterate rows
  jq -c --arg tbl "$table" '.[$tbl][]?' "$JSON" | while read -r row; do
    # Build composite ID from all fields ending in "ID"
    id=$(echo "$row" | jq -r 'to_entries
                              | map(select(.key|test("ID$"))|(.value|tostring))
                              | join(":")')
    [ -z "$id" ] && continue

    # Build HMSET args: key1 val1 key2 val2 …
    args=$(echo "$row" | jq -r 'to_entries
                                | map("\(.key) \(.value|@sh)")
                                | join(" ")')

    echo "HMSET $table:$id $args" >> "$SEED"
  done
done

lines=$(wc -l < "$SEED")
echo "✅  $SEED created ($lines lines)" >&2
