from typing import Dict, Optional

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector import CassandraConnector, MongoDbConnector
from polyfuseql.connector.Connector import Connector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.Redis import RedisConnector
from polyfuseql.config import settings


class ConnectorFactory:
    @staticmethod
    def create_connector(
        conn_type: str,
        catalogue: Catalogue = None,
        options: Optional[Dict] = None,
    ) -> Connector:
        options = options or {}
        if conn_type == "neo4j":
            return Neo4jConnector(catalogue)
        elif conn_type == "postgres":
            return PostgresConnector(catalogue)
        elif conn_type == "redis":
            return RedisConnector(catalogue, options)
        elif conn_type == "cassandra":
            return CassandraConnector(
                catalogue=catalogue,
                options=options,
                settings=settings,
                is_local_implementation=False,
            )
        elif conn_type == "mongodb":
            return MongoDbConnector(
                catalogue=catalogue,
                options=options,
                settings=settings,
                is_local_implementation=False,
            )
        else:
            raise ValueError(f"Unknown connector type: {conn_type}")
