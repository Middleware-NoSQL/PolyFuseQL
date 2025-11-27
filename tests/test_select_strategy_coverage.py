import pytest
import logging
from unittest.mock import MagicMock, AsyncMock
from sqlglot import parse_one
from polyfuseql.strategy.Select import SelectStrategy


@pytest.fixture
def select_strategy():
    return SelectStrategy()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_connector = AsyncMock(return_value=MagicMock())
    # Default mock catalogue
    client._catalogue = {
        "users": {"pk": "id", "backend": "postgres"},
        "broken_table": {"backend": "redis"},  # Missing PK
    }
    return client


@pytest.mark.asyncio
async def test_select_table_not_in_catalogue(select_strategy, mock_client):
    """
    Test Error Path: use_catalogue=True but table is missing.
    Matches logic in _get_pk_column.
    """
    sql = "SELECT * FROM unknown_table WHERE id = 1"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="Table 'unknown_table' not found in catalogue"
    ):
        await select_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_select_no_pk_defined_in_catalogue(select_strategy, mock_client):
    """
    Test Error Path: Table exists but has no PK defined.
    Matches logic in _get_pk_column.
    """
    sql = "SELECT * FROM broken_table WHERE id = 1"
    ast = parse_one(sql)

    with pytest.raises(ValueError, match="No 'pk' defined in catalogue"):
        await select_strategy.execute(
            client=mock_client, ast=ast, backend="redis", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_select_pk_inference_fallback(select_strategy, mock_client, caplog):
    """
    Test Fallback Path: use_catalogue=False.
    Should infer PK from the WHERE clause (left side).
    Matches the 'else' block in _get_pk_column.
    """
    sql = "SELECT * FROM legacy_table WHERE custom_id = 999"
    ast = parse_one(sql)

    # Mock connector response
    mock_conn = MagicMock()
    mock_conn.is_local_implementation = True
    mock_conn.get = AsyncMock(return_value={"custom_id": 999, "name": "test"})
    mock_client.get_connector.return_value = mock_conn

    with caplog.at_level(logging.WARNING):
        result = await select_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=False
        )

    # Verify inference warning
    assert "Inferring PK from WHERE clause: custom_id" in caplog.text
    # Verify get was called with inferred column
    mock_conn.get.assert_awaited_with("legacy_table", "custom_id", 999)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_select_all_warning(select_strategy, mock_client, caplog):
    """
    Test get_all path (no WHERE clause).
    Should trigger the heavy load warning.
    Matches logic in _handle_select_all.
    """
    sql = "SELECT * FROM users"
    ast = parse_one(sql)

    mock_conn = MagicMock()
    mock_conn.is_local_implementation = True
    mock_conn.get_all = AsyncMock(return_value=[{"id": 1}, {"id": 2}])
    mock_client.get_connector.return_value = mock_conn

    with caplog.at_level(logging.WARNING):
        await select_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )

    assert "SELECT queries without a WHERE clause can be heavy" in caplog.text


@pytest.mark.asyncio
async def test_select_connector_not_found(select_strategy, mock_client):
    """
    Test Error Path: Connector returns None.
    Matches first check in execute().
    """
    mock_client.get_connector.return_value = None
    ast = parse_one("SELECT * FROM users")

    with pytest.raises(
        ValueError, match="Connector for backend 'missing_db' not found"
    ):
        await select_strategy.execute(
            client=mock_client, ast=ast, backend="missing_db", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_select_remote_execution(select_strategy, mock_client):
    """
    Test Remote Path: is_local_implementation = False.
    Should bypass local strategies and call conn.query() directly.
    Matches 'Case 0' in execute().
    """
    sql = "SELECT * FROM remote_table"
    ast = parse_one(sql)

    mock_conn = MagicMock()
    mock_conn.is_local_implementation = False  # Triggers the remote path
    mock_conn.query = AsyncMock(return_value=[{"data": "remote"}])
    mock_client.get_connector.return_value = mock_conn

    result = await select_strategy.execute(
        client=mock_client, ast=ast, backend="cassandra", use_catalogue=True
    )

    # Verify query() was called with raw SQL, not get/get_all
    mock_conn.query.assert_awaited_with(sql)
    assert result == [{"data": "remote"}]
