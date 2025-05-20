#!/usr/bin/env sh
# docker/redis/init/build_seed.sh
set -eu

err(){ printf >&2 "❌  %s\n" "$*"; exit 1; }

# ensure jq is present
command -v jq >/dev/null 2>&1 || err "jq not installed"

JSON=${1:-/seed/northwind.json}
SEED=${2:-/seed/seed.redis}

[ -f "$JSON" ] || err "JSON file not found: $JSON"

# show which top‐level keys (tables) we have
echo "🔎  Root keys: $(jq -r 'keys[]' "$JSON" | paste -sd',' -)" >&2

# wipe any old seed file
: > "$SEED"

# for each table...
jq -r 'keys[]' "$JSON" | while read -r table; do
  # ...and each row
  jq -c --arg tbl "$table" '.[$tbl][]?' "$JSON" | while read -r row; do
    # build composite ID from all fields whose key ends with "Id"
    id=$(printf '%s' "$row" |
      jq -r 'to_entries
             | map(select(.key | test("Id$")) | .value | tostring)
             | join(":")')

    [ -z "$id" ] && continue

    # emit a JSON.SET command
    printf "JSON.SET %s:%s . '%s'\n" \
      "$table" "$id" "$(printf '%s' "$row" | jq -c .)" >> "$SEED"
  done
done

lines=$(wc -l < "$SEED")
echo "✅  $SEED created ($lines lines)" >&2
