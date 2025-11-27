import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from pydantic import ValidationError
from polyfuseql.connector.Redis import RedisConnector


# --- Helpers ---
class AsyncIterator:
    """Helper to mock async iterators for 'async for' loops."""

    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        self.iter = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def mock_catalogue():
    # Use a plain MagicMock to avoid issues with spec=Catalogue and dict inheritance
    cat = MagicMock()
    # Default schema response
    cat.get_schema.return_value = {
        "pk": "id",
        "columns": {"id": "str", "name": "str", "age": "int"},
    }
    return cat


@pytest.fixture
def redis_connector(mock_catalogue):
    return RedisConnector(catalogue=mock_catalogue, options={"data_type": "string"})


# --- Tests ---


@pytest.mark.asyncio
async def test_not_connected_error(redis_connector):
    """Targets _get_client raising ConnectionError."""
    redis_connector._client = None
    with pytest.raises(ConnectionError, match="RedisConnector is not connected"):
        redis_connector._get_client()


@pytest.mark.asyncio
async def test_query_not_implemented(redis_connector):
    """Targets query raising NotImplementedError."""
    with pytest.raises(NotImplementedError, match="does not support raw SQL"):
        await redis_connector.query("SELECT * FROM table")


@pytest.mark.asyncio
async def test_get_string_json_decode_error(redis_connector):
    """Targets JSONDecodeError handling in get()."""
    # Mock client
    redis_connector._client = AsyncMock()
    # Simulate invalid JSON string in Redis
    redis_connector._client.get.return_value = "{invalid_json"

    result = await redis_connector.get("User", "id", "1")

    # Should handle error gracefully and return empty dict
    assert result == {}


@pytest.mark.asyncio
async def test_get_validation_error_fallback(redis_connector):
    """Targets ValidationError fallback in get()."""
    redis_connector._client = AsyncMock()
    # Valid JSON, but implies data structure
    redis_connector._client.get.return_value = json.dumps(
        {"id": "1", "name": "Test", "age": "abc"}
    )

    # Mock Pydantic model to raise ValidationError
    with patch("polyfuseql.connector.Redis.get_pydantic_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.side_effect = ValidationError.from_exception_data("Test", [])
        mock_get_model.return_value = mock_model

        result = await redis_connector.get("User", "id", "1")
        # Should fall back to returning raw data on validation error
        assert result["name"] == "Test"


@pytest.mark.asyncio
async def test_insert_primary_key_missing(redis_connector):
    """Targets missing PK check in insert()."""
    # Ensure client is mocked to avoid ConnectionError
    redis_connector._client = AsyncMock()

    # Payload missing 'id' which is the PK
    payload = {"name": "No ID"}

    with pytest.raises(ValueError, match="Primary key value not found"):
        await redis_connector.insert("User", payload)


@pytest.mark.asyncio
async def test_insert_composite_pk_logic(redis_connector, mock_catalogue):
    """Targets composite PK generation in insert()."""
    # Set up schema with composite PK
    mock_catalogue.get_schema.return_value = {
        "pk": ["a", "b"],
        "columns": {"a": "str", "b": "str"},
    }

    redis_connector._client = AsyncMock()
    # Mock pipeline return value
    redis_connector._client.pipeline.return_value.__aenter__.return_value = AsyncMock()

    payload = {"a": "1", "b": "2"}
    result = await redis_connector.insert("User", payload)

    # Verify composite key generation
    assert "1:2" in result["key"]


@pytest.mark.asyncio
async def test_update_key_not_exists(redis_connector):
    """Targets update returning 0 if key doesn't exist."""
    redis_connector._client = AsyncMock()
    redis_connector._client.exists.return_value = False

    count = await redis_connector.update("User", "id", "1", {"name": "New"})
    assert count == 0


@pytest.mark.asyncio
async def test_get_all_parsing_logic(redis_connector):
    """Targets get_all processing logic."""
    redis_connector._client = AsyncMock()

    # FIX 1: scan_iter is a generator, use helper
    redis_connector._client.scan_iter = MagicMock(
        return_value=AsyncIterator(["User:1"])
    )

    # FIX 2: pipeline() call is synchronous in Redis.py (fixed version),
    # so we must mock it as a MagicMock that returns the pipe mock.
    mock_pipe = AsyncMock()
    redis_connector._client.pipeline = MagicMock(return_value=mock_pipe)

    # Mock pipeline execution with mixed valid/invalid/empty data
    mock_pipe.execute.return_value = ['{"id": 1}', None, "{bad_json"]

    results = await redis_connector.get_all("User")

    # Should verify valid data is parsed and invalid/none skipped
    assert len(results) == 1
    assert results[0]["id"] == 1


def test_static_process_redis_results():
    """Targets static _process_redis_results logic used in Spark fallback."""
    # Case 1: Hash type (pass-through)
    res = ["val1", "val2"]
    out = list(RedisConnector._process_redis_results(res, "hash"))
    assert out == res

    # Case 2: String/JSON type with mixed results
    raw_data = ['{"valid": true}', None, "{invalid"]
    out = list(RedisConnector._process_redis_results(raw_data, "json"))
    assert len(out) == 1
    assert out[0]["valid"] is True


@pytest.mark.asyncio
async def test_load_table_hash_spark_exception(redis_connector):
    """Targets exception handling in _load_table_hash_spark."""
    mock_spark = MagicMock()
    # Force an exception during load
    mock_spark.read.format.return_value.schema.return_value.options.return_value.load.side_effect = Exception(  # noqa:E501
        "Spark Error"
    )
    mock_spark.createDataFrame.return_value = "EmptyDF"

    with patch.object(redis_connector, "_get_spark_schema", return_value=MagicMock()):
        redis_connector._options["data_type"] = "hash"
        df = await redis_connector._load_table_to_spark_df("User", mock_spark)
        assert df == "EmptyDF"


@pytest.mark.asyncio
async def test_load_table_fallback_empty_rdd(redis_connector):
    """Targets empty RDD check in fallback loader."""
    mock_spark = MagicMock()
    mock_rdd = MagicMock()
    mock_rdd.isEmpty.return_value = True

    # Simulate empty RDD return
    mock_spark.sparkContext.parallelize.return_value.mapPartitions.return_value = (
        mock_rdd
    )

    redis_connector._client = AsyncMock()
    # FIX: scan_iter must be MagicMock returning AsyncIterator
    redis_connector._client.scan_iter = MagicMock(return_value=AsyncIterator(["key1"]))

    with patch.object(redis_connector, "_get_spark_schema", return_value=MagicMock()):
        redis_connector._options["data_type"] = "json"

        await redis_connector._load_table_to_spark_df("User", mock_spark)  # noqa:E501

        # Should call createDataFrame since RDD was empty
        assert mock_spark.createDataFrame.called


@pytest.mark.asyncio
async def test_get_spark_schema_none(redis_connector, mock_catalogue):
    """Targets ValueError when schema is missing."""
    mock_catalogue.get_schema.return_value = None

    with pytest.raises(ValueError, match="No Spark schema for table"):
        await redis_connector._load_table_to_spark_df("UnknownTable", MagicMock())
