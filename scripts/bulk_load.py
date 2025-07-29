import asyncio
import os
from polyfuseql.connector import PostgresConnector, RedisConnector, Neo4jConnector


async def main():
    # Path to the generated TPC-H data
    data_dir = "/tmp/tpch-data"  # As mounted in the docker-compose file

    # TPC-H tables
    tables = [
        "customer",
        "lineitem",
        "nation",
        "orders",
        "part",
        "partsupp",
        "region",
        "supplier",
    ]

    # Connectors
    pg_connector = PostgresConnector()
    redis_connector = RedisConnector()
    neo4j_connector = Neo4jConnector()

    await pg_connector.connect()
    await redis_connector.connect()
    await neo4j_connector.connect()

    for table in tables:
        file_path = os.path.join(data_dir, f"{table}.tbl")
        if os.path.exists(file_path):
            print(f"Bulk loading {table} into PostgreSQL...")
            pg_count = await pg_connector.bulk_insert(table, file_path)
            print(f"Inserted {pg_count} records into PostgreSQL.")

            print(f"Bulk loading {table} into Redis...")
            redis_count = await redis_connector.bulk_insert(table, file_path)
            print(f"Inserted {redis_count} records into Redis.")

            print(f"Bulk loading {table} into Neo4j...")
            neo4j_count = await neo4j_connector.bulk_insert(table, file_path)
            print(f"Inserted {neo4j_count} nodes into Neo4j.")
        else:
            print(f"File not found: {file_path}")

    await pg_connector.disconnect()
    await redis_connector.disconnect()
    await neo4j_connector.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
