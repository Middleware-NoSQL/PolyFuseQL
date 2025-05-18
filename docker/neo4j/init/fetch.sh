#!/usr/bin/env sh
set -eu

DL () {
  if command -v curl >/dev/null 2>&1; then
      curl -sSL "$1" -o "$2"
  else
      wget -qO "$2" "$1"
  fi
}

if [ ! -f /seed/seed.cypher ]; then
    echo "⇩  Fetching Northwind Cypher"
    DL https://raw.githubusercontent.com/neo4j-graph-examples/northwind/refs/heads/main/scripts/northwind.cypher \
     /seed/seed.cypher
fi
