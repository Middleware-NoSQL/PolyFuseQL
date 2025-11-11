# Activar ambiente
pyenv local 3.12.3
python -m venv .venv && source .venv/bin/activate

sudo systemctl start docker

# Arrancar todo desde cero (carga automática)
sudo docker-compose down -v          # borra volúmenes
sudo docker-compose up -d            # crea y popula

# Arrancar todo desde cero (carga automática)
docker-compose down -v          # borra volúmenes
docker-compose up -d            # crea y popula

docker-compose --profile postgres up -d
docker-compose --profile postgres --profile redis up -d
docker-compose --profile db up -d

# Ver progreso de semillas
sudo docker-compose logs -f redis-seed
sudo docker-compose logs -f neo4j-seed
sudo docker-compose logs -f dbgen

docker-compose logs -f redis
docker-compose logs -f neo4j
docker-compose logs -f dbgen

# Pruebas rápidas
echo "Testing postgres"
#PGPASSWORD="" psql  -h localhost -U northwind -d northwind -c "SELECT COUNT(*) FROM customers;"
PGPASSWORD="" psql  -h localhost -U northwind -d northwind -c "SELECT COUNT(*) FROM \"Customer\";"
echo "Testing redis"
#redis-cli --scan --pattern 'customer:*' | head                                       # claves presentes
redis-cli --scan --pattern 'Customer:*' | head
echo "Testing neo4j"
cypher-shell -u neo4j -p password 'MATCH (p:Product) RETURN count(p);'               # → 77


 export PYSPARK_SUBMIT_ARGS="--jars FILEPATH_TO_JAR pyspark-shell"