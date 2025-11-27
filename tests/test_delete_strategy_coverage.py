import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlglot import parse_one
from polyfuseql.strategy.Delete import DeleteStrategy


@pytest.fixture
def delete_strategy():
    return DeleteStrategy()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_connector = AsyncMock(return_value=MagicMock())
    # Mock the catalogue as a dictionary
    client._catalogue = {"users": {"pk": "id", "backend": "postgres"}}
    return client


@pytest.mark.asyncio
async def test_delete_table_not_in_catalogue(delete_strategy, mock_client):
    """
    Test Error Path 1: use_catalogue=True but table is missing from catalogue.
    """
    sql = "DELETE FROM unknown_table WHERE id = 1"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="Table 'unknown_table' not found in catalogue"
    ):
        await delete_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_delete_pk_mismatch(delete_strategy, mock_client):
    """
    Test Error Path 2: The WHERE clause column does not match the Catalogue PK.
    Catalogue PK for 'users' is 'id', query uses 'email'.
    """
    sql = "DELETE FROM users WHERE email = 'test@test.com'"
    ast = parse_one(sql)

    with pytest.raises(
        ValueError, match="DELETE on table 'users' must use the primary key 'id'"
    ):
        await delete_strategy.execute(
            client=mock_client, ast=ast, backend="postgres", use_catalogue=True
        )


@pytest.mark.asyncio
async def test_delete_non_literal_where(delete_strategy, mock_client):
    """
    Test Error Path 3: The WHERE clause compares against a
    column/expression, not a literal.
    """
    # Simulate a query like DELETE FROM users WHERE id = other_column
    # We manually construct a weird AST or just parse a query that
    # sqlglot interprets as non-literal
    sql = "DELETE FROM users WHERE id = other_col"
    ast = parse_one(sql)

    with pytest.raises(
        NotImplementedError, match="DELETE WHERE clause requires a literal value"
    ):
        await delete_strategy.execute(
            client=mock_client,
            ast=ast,
            backend="postgres",
            use_catalogue=True,  # Catalogue check passes, fails on literal check
        )
