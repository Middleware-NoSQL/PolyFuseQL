from typing import Dict

from polyfuseql.connector.Connector import Connector
from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.connector.Postgres import PostgresConnector
from polyfuseql.connector.Redis import RedisConnector


class ConnectorFactory:
    @staticmethod
    def create_connector(conn_type: str, options: Dict = None) -> Connector:
        if conn_type == "neo4j":
            return Neo4jConnector(options)
        elif conn_type == "postgres":
            return PostgresConnector(options)
        elif conn_type == "redis":
            return RedisConnector(options)
        else:
            raise ValueError(f"Unknown connector type: {conn_type}")
