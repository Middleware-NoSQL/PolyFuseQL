"""polyfuseql.config
~~~~~~~~~~~~~~~~~~~~~
Centralized configuration management using Pydantic settings.

This module defines a unified, type-validated configuration model for all
application settings, including database connections and Spark parameters.
It loads settings from environment variables and a .env file, providing a
single source of truth throughout the application.
"""

from pathlib import Path
from typing import Optional, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    Defines the complete configuration for the application, loading values
    from environment variables or a .env file.
    """

    # Pydantic settings configuration
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # PostgreSQL Settings
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "tpch"
    postgres_password: str = "tpch"
    postgres_db: str = "tpch"

    # Redis Settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "tpch"
    # The default data type strategy for Redis. Can be overridden at runtime.
    redis_data_type: Literal["hash", "string", "json"] = "hash"

    # Neo4j Settings
    neo4j_host: str = "localhost"
    neo4j_port: int = 7687
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_spark_jar_path: Optional[str] = (
        "./jars/neo4j-spark-connector-5.3.1-s_2.13.jar"
    )

    # Spark Settings
    spark_master_url: str = "local[*]"
    spark_app_name_prefix: str = "PolyFuseQL-TPCH-Benchmark"
    spark_driver_memory: str = "4g"
    spark_executor_memory: str = "3g"
    spark_cores_max: str = "48"
    spark_shuffle_partitions: str = "144"
    spark_network_timeout: str = "8000s"
    spark_executor_heartbeat_interval: str = "60s"

    # Application-specific Settings
    polyfuseql_schema_path: Path = Path("schemas.json")


# Singleton instance to be used across the application
settings = AppSettings()
