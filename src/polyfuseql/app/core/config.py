# app/core/config.py
"""
Configuration management for the FastAPI application.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings.
    """

    # PostgreSQL settings
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "tpch")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "tpch")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "tpch")

    # Redis settings
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "tpch")

    # Neo4j settings
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

    # Cassandra settings
    CASSANDRA_HOST: str = os.getenv("CASSANDRA_HOST", "localhost")
    CASSANDRA_PORT: int = int(os.getenv("CASSANDRA_PORT", 9043))
    CASSANDRA_USER: str = os.getenv("CASSANDRA_USER", "cassandra")
    CASSANDRA_PASSWORD: str = os.getenv("CASSANDRA_PASSWORD", "cassandra")
    CASSANDRA_KEYSPACE: str = os.getenv("CASSANDRA_KEYSPACE", "mykeyspace")

    # MongoDB settings
    MONGODB_USER: str = os.getenv("MONGODB_USER", "root")
    MONGODB_PASSWORD: str = os.getenv("MONGODB_PASSWORD", "example")
    MONGODB_HOST: str = os.getenv("MONGODB_HOST", "localhost")
    MONGODB_PORT: int = int(os.getenv("MONGODB_PORT", 27018))
    MONGODB_DB: str = os.getenv("MONGODB_DB", "mydatabase")

    # Pydantic V2 Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
