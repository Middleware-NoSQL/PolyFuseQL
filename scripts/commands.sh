# Activar ambiente
pyenv local 3.12.3
python -m venv .venv && source .venv/bin/activate

sudo systemctl start docker

# Arrancar todo desde cero (carga automática)
sudo docker-compose down -v          # borra volúmenes
sudo docker-compose up -d            # crea y popula

# Arrancar todo desde cero (carga automática)
docker-compose down -v          # borra volúmenes
docker network prune            # borra redes no usadas
docker-compose up -d            # crea y popula

docker-compose --profile postgres up -d
docker-compose --profile postgres --profile redis up -d
docker-compose --profile postgres --profile redis --profile neo4j up -d
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


# We stop all containers to release any potential network locks.
# We use '|| true' to prevent the script from exiting if no containers are running.
sudo docker stop $(sudo docker ps -q)

# This is the most important step to remove the "ghost" containers
# that are holding the hard-coded names from your docker-compose.yml file.
# It is OK if this says "No such container".
sudo docker rm -f \
  polyfuseql_tpch_dbgen \
  polyfuseql_pg_tpch \
  polyfuseql_redis_kv \
  polyfuseql_neo4j_graph \
  polyfuseql_mongodb \
  polyfuseql_cassandra \
  polyfuseql_mongo_translator \
  polyfuseql_cassandra_translator \
  polyfuseql_cassandra_translator_auth \
  polyfuseql_cassandra_translator_permission

# This cleans up any other resources Docker thinks belong to this project.
sudo docker compose down --remove-orphans -v

# This clears Docker's corrupted in-memory state (the ghost network error).
sudo systemctl restart docker

# This finally removes the "ghost" network references.
sudo docker network prune -f

uvicorn polyfuseql.app.main:app --reload --log-level debug
