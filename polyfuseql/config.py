"""polyfuseql.config
~~~~~~~~~~~~~~~~~~~~~
Centralized configuration management using Pydantic settings.

This module defines a unified, type-validated configuration model for all
application settings, including database connections and Spark parameters.
It loads settings from environment variables and a .env file, providing a
single source of truth throughout the application.
"""

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseModel):
    user: str = "postgres"
    password: str = "password"
    host: str = "postgres"
    port: int = 5432
    db: str = "tpch"


class RedisSettings(BaseModel):
    host: str = "redis"
    port: int = 6379
    db: int = 0


class Neo4jSettings(BaseModel):
    uri: str = "bolt://neo4j:7687"
    user: str = "neo4j"
    password: str = "password"


class MongoDbSettings(BaseModel):
    user: str = "root"
    password: str = "example"
    host: str = "mongodb"
    port: int = 27017
    db: str = "mydatabase"


class CassandraSettings(BaseModel):
    user: str | None = None
    password: str | None = None
    host: str = "cassandra"
    port: int = 9042
    keyspace: str = "mykeyspace"


class SparkSettings(BaseModel):
    master_url: str = "local[*]"
    app_name_prefix: str = "PolyFuseQL-TPCH-Benchmark"
    driver_memory: str = "4g"
    executor_memory: str = "3g"
    cores_max: str = "48"
    shuffle_partitions: str = "144"
    network_timeout: str = "8000s"
    executor_heartbeat_interval: str = "60s"


class AppSettings(BaseSettings):
    """
    Defines the complete configuration for the application, loading values
    from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    mongodb: MongoDbSettings = Field(default_factory=MongoDbSettings)
    cassandra: CassandraSettings = Field(default_factory=CassandraSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)

    mongo_translator_url: str = "http://mongo-translator-api:5000"
    cassandra_translator_url: str = "http://cassandra-translator-api:3000"

    # Application-specific Settings
    polyfuseql_schema_path: Path = Path("schemas.json")


# Singleton instance to be used across the application
settings = AppSettings()
