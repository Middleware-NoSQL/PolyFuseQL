import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlglot import parse_one
from polyfuseql.strategy.Join import JoinStrategy


@pytest.fixture
def join_strategy():
    return JoinStrategy()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_connector = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_join_strategy_success(join_strategy, mock_client):
    """
    Test Happy Path: Backend exists, Connector exists, join() is called.
    Matches Line 20 in Join.py.
    """
    # Setup
    backend = "postgres"
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id"
    ast = parse_one(sql)

    # Mock the connector returned by the client
    mock_conn = MagicMock()
    expected_result = [{"id": 1, "val": "a"}]
    mock_conn.join = AsyncMock(return_value=expected_result)
    mock_client.get_connector.return_value = mock_conn

    # Execute
    result = await join_strategy.execute(
        client=mock_client, ast=ast, backend=backend, use_catalogue=False
    )

    # Assert assertions
    mock_client.get_connector.assert_awaited_once_with(backend)
    mock_conn.join.assert_awaited_once_with(ast)
    assert result == expected_result


@pytest.mark.asyncio
async def test_join_strategy_missing_backend(join_strategy, mock_client):
    """
    Test Error Path 1: Backend argument is None or empty.
    Matches Lines 11-13 in Join.py.
    """
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id"
    ast = parse_one(sql)

    # Case 1: None
    with pytest.raises(
        ValueError, match="An 'engine' must be specified for JOIN operations"
    ):
        await join_strategy.execute(
            client=mock_client, ast=ast, backend=None, use_catalogue=False
        )

    # Case 2: Empty string
    with pytest.raises(
        ValueError, match="An 'engine' must be specified for JOIN operations"
    ):
        await join_strategy.execute(
            client=mock_client, ast=ast, backend="", use_catalogue=False
        )


@pytest.mark.asyncio
async def test_join_strategy_connector_not_found(join_strategy, mock_client):
    """
    Test Error Path 2: Backend specified, but connector returns None.
    Matches Lines 16-17 in Join.py.
    """
    backend = "unknown_db"
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id"
    ast = parse_one(sql)

    # Simulate connector not found
    mock_client.get_connector.return_value = None

    with pytest.raises(
        ValueError, match=f"Connector for backend '{backend}' not found"
    ):
        await join_strategy.execute(
            client=mock_client, ast=ast, backend=backend, use_catalogue=False
        )
