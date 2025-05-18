#!/usr/bin/env sh
sudo docker-compose down -v          # borra volúmenes
sudo docker-compose up -d

echo "Testing postgres"
PGPASSWORD=northwind psql  -h localhost -U northwind -d northwind -c "SELECT COUNT(*) FROM customers;"
echo "Testing redis"
redis-cli --scan --pattern 'customer:*' | head
echo "Testing neo4j"
cypher-shell -u neo4j -p password 'MATCH (p:Product) RETURN count(p);'