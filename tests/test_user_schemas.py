# tests/test_user_schemas.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock
from polyfuseql.client.PolyClient import PolyClient
from polyfuseql.catalogue.Catalogue import Catalogue


@pytest.fixture
def valid_schema_file(tmp_path: Path) -> Path:
    """Creates a temporary valid schema JSON file for testing."""
    schema_content = {
        "test_table": {
            "backend": "postgres",
            "pk": "id",
            "columns": {"id": "int", "name": "str"},
        }
    }
    schema_file = tmp_path / "valid_schema.json"
    schema_file.write_text(json.dumps(schema_content))
    return schema_file


@pytest.fixture
def malformed_json_file(tmp_path: Path) -> Path:
    """Creates a temporary malformed JSON file."""
    malformed_file = tmp_path / "malformed.json"
    # Missing a closing brace to make it invalid JSON
    malformed_file.write_text(
        '{"test_table": {"backend": "postgres", "pk": "id"'
    )  # noqa:F501
    return malformed_file


@pytest.fixture
def incomplete_schema_file(tmp_path: Path) -> Path:
    """Creates a temporary schema file that is missing required keys."""
    schema_content = {
        "test_table": {"backend": "postgres"}
    }  # Missing 'pk' and 'columns'
    incomplete_file = tmp_path / "incomplete.json"
    incomplete_file.write_text(json.dumps(schema_content))
    return incomplete_file


@pytest.mark.asyncio
async def test_load_valid_custom_schema(valid_schema_file: Path):
    """Tests that a valid custom schema file is loaded correctly."""
    async with PolyClient(schema_path=valid_schema_file) as client:
        assert "test_table" in client.catalogue
        schema = client.catalogue.get_schema("test_table")
        assert schema["backend"] == "postgres"
        assert schema["pk"] == "id"


@pytest.mark.asyncio
async def test_load_nonexistent_schema_raises_error():
    """
    Tests that initializing with a non-existent schema path raises an error.
    """
    with pytest.raises(FileNotFoundError):
        Catalogue(schema_path="/path/to/nonexistent/schema.json")


@pytest.mark.asyncio
async def test_load_schema_from_env_var(valid_schema_file: Path, monkeypatch):
    """
    Tests that the schema is loaded from the path specified
    in the environment variable.
    """
    monkeypatch.setenv("POLYFUSEQL_SCHEMA_PATH", str(valid_schema_file))
    async with PolyClient() as client:
        assert "test_table" in client.catalogue
        assert (
            client.catalogue.get_schema("test_table")["backend"] == "postgres"
        )  # noqa:F501


@pytest.mark.asyncio
async def test_load_malformed_json_schema(malformed_json_file: Path):
    """Tests that a malformed JSON schema file raises a ValueError."""
    with pytest.raises(ValueError) as excinfo:
        Catalogue(schema_path=malformed_json_file)
    assert "Invalid JSON" in str(excinfo.value)


@pytest.mark.asyncio
async def test_load_incomplete_schema(incomplete_schema_file: Path):
    """Tests that a schema missing required keys raises a ValueError."""
    with pytest.raises(ValueError) as excinfo:
        Catalogue(schema_path=incomplete_schema_file)
    # Check that the error message mentions all missing keys
    error_message = str(excinfo.value)
    assert "Missing required key(s)" in error_message
    assert "pk" in error_message
    assert "columns" in error_message


@pytest.mark.asyncio
async def test_schema_usage_in_get_operation(valid_schema_file: Path):
    """
    Verifies that the loaded schema is used for operations like 'get'.
    This is a mock test to demonstrate the principle without a live DB.
    """

    # The signature must include 'self' as it's mocking an instance method.
    async def mock_get(self, table, pk_col, pk_val):
        return {"table": table, "pk_col": pk_col, "pk_val": pk_val}

    with (
        patch("polyfuseql.connector.PostgresConnector.get", new=mock_get),
        patch(
            "polyfuseql.connector.PostgresConnector.connect", new=AsyncMock()
        ),  # noqa:F501
        patch("polyfuseql.connector.RedisConnector.connect", new=AsyncMock()),
        patch("polyfuseql.connector.Neo4jConnector.connect", new=AsyncMock()),
    ):
        async with PolyClient(schema_path=valid_schema_file) as client:
            # Corrected call: Pass the PK value. The PolyClient should look up
            # the PK column name ('id') from the loaded schema.
            result = await client.get("test_table", 123)

            # Assert that the mock received the correct parameters,
            # with 'pk_col' correctly inferred from the schema.
            assert result["table"] == "test_table"
            assert result["pk_col"] == "id"
            assert result["pk_val"] == 123
