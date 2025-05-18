#!/usr/bin/env sh
# Convert northwind.json → seed.redis  (Customer + Product)
set -euo pipefail

err(){ printf >&2 "❌  %s\n" "$*"; exit 1; }
command -v jq >/dev/null 2>&1 || err "jq not installed"

JSON=${1:-/seed/northwind.json}
[ -f "$JSON" ] || err "JSON file not found: $JSON"

echo "🔎  Root keys: $(jq -c 'keys' "$JSON")" >&2

emit_set(){ echo "SET $1 '$(echo "$2" | jq -c '.')'"; }

count_c=0; count_p=0
CUST='.Customer[]?'
PROD='.Product[]?'

# ── Customers ────────────────────────────────────────────
jq -c "$CUST" "$JSON" | while read -r row; do
  id=$(echo "$row" | jq -r '
        .customerId // .CustomerID // .entityId // .id // empty')
  [ -z "$id" ] && continue
  emit_set "customer:${id}" "$row"
  count_c=$((count_c+1))
done

# ── Products ─────────────────────────────────────────────
jq -c "$PROD" "$JSON" | while read -r row; do
  id=$(echo "$row" | jq -r '
        .productId // .ProductID // .entityId // .id // empty')
  [ -z "$id" ] && continue
  emit_set "product:${id}" "$row"
  count_p=$((count_p+1))
done

printf >&2 "✔️  Generated %d customers and %d products\n" "$count_c" "$count_p"
