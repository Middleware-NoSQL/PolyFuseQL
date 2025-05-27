#!/usr/bin/env sh
# docker/redis/init/build_seed.sh
# Emits SET, HSET, HMSET & JSON.SET for Customer + Product
# with a live progress bar.

set -eu

err(){ printf >&2 "❌  %s\n" "$*"; exit 1; }
command -v jq >/dev/null 2>&1 || err "jq not installed"

JSON=${1:-/seed/northwind.json}
SEED=${2:-/seed/seed.redis}
[ -f "$JSON" ] || err "JSON file not found: $JSON"

# 1) figure out how many records we’ll process
cust_len=$(jq '.Customer | length' "$JSON")
prod_len=$(jq '.Product  | length' "$JSON")
total=$((cust_len + prod_len))
[ "$total" -gt 0 ] || err "No Customer or Product records found in $JSON"

echo "🔎  Found $cust_len customers and $prod_len products (total $total)" >&2

# 2) clear out any old seed
: > "$SEED"

processed=0

# helper to JSON-quote a string for safe Redis SET/JSON.SET
quote_json() {
  printf '%s' "$1" | jq -aRs .
}

# 3) main loop over the two entities
for entity in Customer Product; do
  len=$(jq ".${entity} | length" "$JSON")
  i=0
  while [ "$i" -lt "$len" ]; do
    # pull the i-th record
    row=$(jq -c ".${entity}[${i}]" "$JSON")

    # update progress
    processed=$((processed+1))
    percent=$((processed * 100 / total))
    bar_len=$((percent * 50 / 100))
    bar="$(printf "%${bar_len}s" | tr ' ' '=')"
    printf "\rProgress: [%-50s] %3d%% (%d/%d)" \
           "$bar" "$percent" "$processed" "$total" >&2

    # compute composite ID from all fields ending in "Id"
    id=$(printf '%s' "$row" |
         jq -r 'to_entries
                | map(select(.key|test("Id$"))|.value|tostring)
                | join(":")')
    if [ -n "$id" ]; then
      key_base="${entity}:${id}"
      raw=$(printf '%s' "$row" | jq -c .)

      # build "field value ..." for HSET/HMSET
      args=$(printf '%s' "$row" |
             jq -r 'to_entries
                    | map("\(.key) \(.value|tostring|@sh)")
                    | join(" ")')

      # 1) simple string
      echo "SET ${key_base}:string $(quote_json "$raw")" >> "$SEED"
      # 2) basic hash
      echo "HSET ${key_base}:hash $args" >> "$SEED"
      # 3) JSON (ReJSON)
      echo "JSON.SET ${key_base}:json . $(quote_json "$raw")" >> "$SEED"
    fi

    i=$((i+1))
  done
done

# finish the progress bar line
printf "\n" >&2

lines=$(wc -l < "$SEED")
echo "✅  $SEED created ($lines lines)" >&2
