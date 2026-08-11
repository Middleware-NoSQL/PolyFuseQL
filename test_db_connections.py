import psycopg2
import redis
from pymongo import MongoClient
from neo4j import GraphDatabase
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider

# These hostnames match the 'container_name' in your docker-compose.yml[cite: 9]
SERVICES = {
    "postgres": {"host": "polyfuseql_pg_tpch", "port": 5432},
    "redis": {"host": "polyfuseql_redis_kv", "port": 6379},
    "mongodb": {"host": "polyfuseql_mongodb", "port": 27017},
    "neo4j": {"host": "polyfuseql_neo4j_graph", "port": 7687},
    "cassandra": {"host": "polyfuseql_cassandra", "port": 9042}
}

def test_postgres():
    print("Testing PostgreSQL...")
    try:
        conn = psycopg2.connect(
            host=SERVICES["postgres"]["host"],
            port=SERVICES["postgres"]["port"],
            dbname="tpch",
            user="tpch",
            password="tpch"
        )
        print("✅ PostgreSQL: Connected successfully.")
        conn.close()
    except Exception as e:
        print(f"❌ PostgreSQL failed: {e}")

def test_redis():
    print("Testing Redis...")
    try:
        r = redis.Redis(
            host=SERVICES["redis"]["host"],
            port=SERVICES["redis"]["port"],
            password="tpch",
            socket_timeout=5
        )
        if r.ping():
            print("✅ Redis: Connected successfully.")
    except Exception as e:
        print(f"❌ Redis failed: {e}")

def test_mongodb():
    print("Testing MongoDB...")
    try:
        # Internal container port is 27017[cite: 9]
        client = MongoClient(
            f"mongodb://root:example@{SERVICES['mongodb']['host']}:{SERVICES['mongodb']['port']}/",
            serverSelectionTimeoutMS=5000
        )
        client.server_info()
        print("✅ MongoDB: Connected successfully.")
    except Exception as e:
        print(f"❌ MongoDB failed: {e}")

def test_neo4j():
    print("Testing Neo4j...")
    try:
        driver = GraphDatabase.driver(
            f"bolt://{SERVICES['neo4j']['host']}:{SERVICES['neo4j']['port']}", 
            auth=("neo4j", "password")
        )
        driver.verify_connectivity()
        print("✅ Neo4j: Connected successfully.")
        driver.close()
    except Exception as e:
        print(f"❌ Neo4j failed: {e}")

def test_cassandra():
    print("Testing Cassandra...")
    try:
        # Internal container port is 9042[cite: 9]
        auth_provider = PlainTextAuthProvider(username="cassandra", password="cassandra")
        cluster = Cluster([SERVICES["cassandra"]["host"]], port=SERVICES["cassandra"]["port"], auth_provider=auth_provider)
        session = cluster.connect()
        print("✅ Cassandra: Connected successfully.")
        cluster.shutdown()
    except Exception as e:
        print(f"❌ Cassandra failed: {e}")

if __name__ == "__main__":
    test_postgres()
    test_redis()
    test_mongodb()
    test_neo4j()
    test_cassandra()
