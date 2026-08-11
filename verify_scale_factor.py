import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'src')))
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.MongoDb import MongoDbConnector
from polyfuseql.connector.Cassandra import CassandraConnector
from polyfuseql.connector.Redis import RedisConnector

load_dotenv()

async def verify_scale_factor():
    print("="*60)
    print("TPC-H Scale Factor 10 Verification")
    print("Expected 'orders' count: 15,000,000")
    print("Expected 'region' count: 5")
    print("="*60)

    # 1. POSTGRES
    try:
        pg = PostgresConnector("relational")
        await pg.connect()
        res = await pg.execute_query("SELECT COUNT(*) as cnt FROM orders", fetch=True)
        print(f"✅ Postgres 'orders' count: {res[0]['cnt']:,}")
        await pg.disconnect()
    except Exception as e:
        print(f"❌ Postgres check failed: {e}")

    # 2. NEO4J
    try:
        neo = Neo4jConnector("graph")
        await neo.connect()
        # Neo4j uses graph querying, so we count Order labels
        res = await neo.execute_query("MATCH (n:Order) RETURN count(n) as cnt")
        # Neo4j pyspark connector returns DataFrame or driver? If this uses the python driver:
        # Actually PolyFuseQL neo4j connector returns lists of dicts usually.
        print(f"✅ Neo4j 'Order' nodes: {res[0]['cnt'] if res else 'Unknown'}")
        await neo.disconnect()
    except Exception as e:
        print(f"❌ Neo4j check failed: {e}")

    # 3. MONGODB
    try:
        mongo = MongoDbConnector("doc")
        await mongo.connect()
        # In MongoDB, the connector exposes db/collection
        db = mongo.client[mongo.database]
        count = await db["orders"].count_documents({})
        print(f"✅ MongoDB 'orders' documents: {count:,}")
        await mongo.disconnect()
    except Exception as e:
        print(f"❌ MongoDB check failed: {e}")

    # 4. CASSANDRA
    try:
        cas = CassandraConnector("wide")
        await cas.connect()
        # Cassandra count(*) can be very slow or timeout on large tables without limit
        # but for 15M it might execute if timeouts are generous. 
        # Alternatively, we just check limit 1
        res = await cas.execute_query("SELECT COUNT(*) FROM orders")
        # Extract count depending on cassandra driver return format
        cnt = res[0].count if res else 0
        print(f"✅ Cassandra 'orders' count: {cnt:,}")
        await cas.disconnect()
    except Exception as e:
        print(f"❌ Cassandra check failed: {e}")

    # 5. REDIS
    try:
        redis = RedisConnector("string")
        await redis.connect()
        # Redis keys for orders string
        # Assuming keys are formatted like tpch:string:orders:*
        keys = await redis.redis.keys("tpch:string:orders:*")
        print(f"✅ Redis 'orders' (string) keys found: {len(keys):,}")
        await redis.disconnect()
    except Exception as e:
        print(f"❌ Redis check failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_scale_factor())
