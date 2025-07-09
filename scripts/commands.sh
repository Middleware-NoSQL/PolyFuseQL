# Activar ambiente
pyenv local 3.12.3
python -m venv .venv && source .venv/bin/activate

sudo systemctl start docker

# Arrancar todo desde cero (carga automática)
sudo docker-compose down -v          # borra volúmenes
sudo docker-compose up -d            # crea y popula

# Ver progreso de semillas
sudo docker-compose logs -f redis-seed
sudo docker-compose logs -f neo4j-seed

# Pruebas rápidas
echo "Testing postgres"
#PGPASSWORD="" psql  -h localhost -U northwind -d northwind -c "SELECT COUNT(*) FROM customers;"
PGPASSWORD="" psql  -h localhost -U northwind -d northwind -c "SELECT COUNT(*) FROM \"Customer\";"
echo "Testing redis"
#redis-cli --scan --pattern 'customer:*' | head                                       # claves presentes
redis-cli --scan --pattern 'Customer:*' | head
echo "Testing neo4j"
cypher-shell -u neo4j -p password 'MATCH (p:Product) RETURN count(p);'               # → 77
