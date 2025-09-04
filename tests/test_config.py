"""
Tests for the centralized Pydantic configuration model.
"""

import pytest
from pydantic import ValidationError
from pathlib import Path, PosixPath


def test_default_settings_load(monkeypatch):
    """Test that default settings are loaded when no env vars are set."""
    # Ensure no relevant env vars are set for a clean test
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)
    monkeypatch.delenv("POLYFUSEQL_SCHEMA_PATH", raising=False)

    # Re-importing the module forces pydantic-settings to re-evaluate
    from polyfuseql import config
    import importlib

    importlib.reload(config)

    settings = config.settings
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.redis_port == 6379
    assert settings.polyfuseql_schema_path == PosixPath("schemas.json")


def test_env_var_override(monkeypatch):
    """Test that environment variables correctly override default settings."""
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("REDIS_PORT", "1234")
    monkeypatch.setenv("POLYFUSEQL_SCHEMA_PATH", "/tmp/custom_schema.json")

    from polyfuseql import config
    import importlib

    importlib.reload(config)

    settings = config.settings
    assert settings.postgres_host == "db.example.com"
    assert settings.redis_port == 1234
    assert settings.polyfuseql_schema_path == Path("/tmp/custom_schema.json")


def test_env_file_loading(monkeypatch, tmp_path):
    """Test that settings are correctly loaded from a .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_USER=testuser\nNEO4J_HOST=neo4j.local")

    # Change current working directory so pydantic-settings finds the .env file
    monkeypatch.chdir(tmp_path)

    from polyfuseql import config
    import importlib

    importlib.reload(config)

    settings = config.settings
    assert settings.postgres_user == "testuser"
    assert settings.neo4j_host == "neo4j.local"
    # Verify a default value remains if not in the .env file
    assert settings.redis_host == "localhost"


def test_type_validation_error(monkeypatch):
    """
    Test that Pydantic raises a validation error for incorrect data types.
    """
    monkeypatch.setenv("POSTGRES_PORT", "not-a-number")

    from polyfuseql import config
    import importlib

    # The settings object is created at import time, so reloading the module
    # will trigger the validation error.
    with pytest.raises(ValidationError):
        importlib.reload(config)
