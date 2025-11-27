import pytest
import importlib
from polyfuseql.app.core import config


@pytest.fixture
def clean_env(monkeypatch):
    """
    Clears relevant environment variables to ensure defaults are tested.
    """
    vars_to_clear = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "CASSANDRA_HOST",
        "CASSANDRA_PORT",
        "CASSANDRA_USER",
        "CASSANDRA_PASSWORD",
        "CASSANDRA_KEYSPACE",
        "MONGODB_USER",
        "MONGODB_PASSWORD",
        "MONGODB_HOST",
        "MONGODB_PORT",
        "MONGODB_DB",
    ]
    for var in vars_to_clear:
        monkeypatch.delenv(var, raising=False)


def test_app_config_defaults(clean_env):
    """
    Targets: Default values in Settings class.
    Verifies that os.getenv returns the fallback when env vars are unset.
    """
    # Reload module to re-evaluate class definitions with cleared env
    importlib.reload(config)
    settings = config.Settings()

    # Postgres Defaults
    assert settings.POSTGRES_USER == "tpch"
    assert settings.POSTGRES_PORT == 5432

    # Redis Defaults
    assert settings.REDIS_HOST == "localhost"
    assert settings.REDIS_PORT == 6379

    # Neo4j Defaults
    assert settings.NEO4J_USER == "neo4j"

    # Cassandra Defaults
    assert settings.CASSANDRA_PORT == 9043

    # Mongo Defaults
    assert settings.MONGODB_PORT == 27018


def test_app_config_overrides(monkeypatch):
    """
    Targets: Environment variable overrides.
    Verifies that os.getenv picks up set values.
    """
    overrides = {
        "POSTGRES_USER": "custom_pg_user",
        "POSTGRES_PORT": "9999",
        "REDIS_HOST": "custom_redis",
        "NEO4J_URI": "bolt://custom:7687",
        "CASSANDRA_KEYSPACE": "custom_keyspace",
        "MONGODB_DB": "custom_mongo_db",
    }

    for key, val in overrides.items():
        monkeypatch.setenv(key, val)

    # Reload module to re-evaluate class definitions with new env vars
    importlib.reload(config)
    settings = config.Settings()

    assert settings.POSTGRES_USER == "custom_pg_user"
    assert settings.POSTGRES_PORT == 9999
    assert settings.REDIS_HOST == "custom_redis"
    assert settings.NEO4J_URI == "bolt://custom:7687"
    assert settings.CASSANDRA_KEYSPACE == "custom_keyspace"
    assert settings.MONGODB_DB == "custom_mongo_db"


def test_singleton_instantiation():
    """
    Targets: The global 'settings = Settings()' line at the end of the file.
    """
    importlib.reload(config)
    assert isinstance(config.settings, config.Settings)
