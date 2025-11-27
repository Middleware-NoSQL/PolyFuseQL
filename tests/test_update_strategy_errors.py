import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlglot import parse_one
from polyfuseql.strategy.Update import UpdateStrategy


@pytest.fixture
def update_strategy():
    return UpdateStrategy()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_connector = AsyncMock(return_value=MagicMock())
    # Mock catalogue with a valid entry and one missing a PK
    client._catalogue = {
        "users": {"pk": "id", "backend": "postgres"},
        "broken_table": {"backend": "redis"},  # Missing 'pk' key
    }
    return client


@pytest.mark.asyncio
async def test_update_table_not_in_catalogue(update_strategy, mock_client):
    """
    Test that updating a table not present in the catalogue raises ValueError.
    """
    sql = "UPDATE unknown_table SET name='test' WHERE id=1"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="Table 'unknown_table' not found in catalogue"
    ):
        await update_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_update_no_pk_in_catalogue_definition(update_strategy, mock_client):
    """
    Test schema validation: Catalogue entry exists but lacks 'pk' definition.
    """
    sql = "UPDATE broken_table SET name='test' WHERE id=1"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="No 'pk' defined in catalogue for table 'broken_table'"
    ):
        await update_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_update_pk_mismatch_in_where_clause(update_strategy, mock_client):
    """
    Test query validation: The WHERE clause uses a column different from the defined PK.
    """
    sql = "UPDATE users SET name='test' WHERE email='wrong@col.com'"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="must use the primary key 'id' in WHERE clause"
    ):
        await update_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_update_connector_not_found(update_strategy, mock_client):
    """
    Test that a missing connector raises the appropriate error.
    """
    # Simulate get_connector returning None
    mock_client.get_connector = AsyncMock(return_value=None)

    sql = "UPDATE users SET name='test' WHERE id=1"
    ast = parse_one(sql)

    with pytest.raises(ValueError, match="Connector for backend 'postgres' not found"):
        await update_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )
