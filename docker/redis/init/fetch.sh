#!/usr/bin/env sh
set -eu

# Downloader that works with or without curl
DL () {
  if command -v curl >/dev/null 2>&1; then
       curl -sSL "$1" -o "$2"
  else
       wget -qO "$2" "$1"
  fi
}

JSON=/seed/northwind.json
SEED=/seed/seed.redis


echo "⇩  Fetching Northwind JSON"
DL https://raw.githubusercontent.com/harryho/db-samples/master/json/json_data.min.json "$JSON"

echo "✅  JSON Downloaded"

