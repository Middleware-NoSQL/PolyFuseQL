import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pydantic import BaseModel
from sqlglot import parse_one

from polyfuseql.connector.Neo4j import Neo4jConnector
from polyfuseql.catalogue.Catalogue import Catalogue

# --- Helpers ---


class MockModel(BaseModel):
    id: int
    name: str


class AsyncIterator:
    """
    A robust helper to mock async iterators for 'async for' loops.
    This fixes the 'TypeError: async_generator object is not iterable' issue
    encountered with standard MagicMock.__aiter__.
    """

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


# --- Fixtures ---


@pytest.fixture
def connector():
    catalogue = MagicMock(spec=Catalogue)
    catalogue.get_schema.return_value = {
        "columns": {"id": "int", "name": "str"},
        "pk": "id",
    }
    return Neo4jConnector(catalogue=catalogue)


# --- Tests ---


@pytest.mark.asyncio
async def test_get_driver_not_connected(connector):
    """
    Targets: _get_driver raising ConnectionError (Image 3, Line 93).
    """
    connector._driver = None
    with pytest.raises(ConnectionError, match="Neo4jConnector is not connected"):
        connector._get_driver()


@pytest.mark.asyncio
async def test_query_not_implemented(connector):
    """
    Targets: query raising NotImplementedError (Image 4, Line 317).
    """
    with pytest.raises(NotImplementedError, match="Neo4jConnector expects Cypher"):
        await connector.query("SELECT * FROM table")


@pytest.mark.asyncio
async def test_get_all_logic(connector):
    """
    Targets: get_all method logic, where_clause,
    and async iteration.
    Uses AsyncIterator helper to fix the mocking crash.
    """
    # Mock the driver and session
    mock_driver = MagicMock()
    mock_session = AsyncMock()
    mock_driver.session.return_value = mock_session
    connector._driver = mock_driver

    # Prepare mock data
    mock_records = [{"p": {"id": 1, "name": "test"}}]

    # 1. Test without WHERE clause
    # We create a fresh iterator for each run
    mock_session.__aenter__.return_value.run.return_value = AsyncIterator(mock_records)

    results = await connector.get_all("Customer")
    assert len(results) == 1
    assert results[0]["id"] == 1

    # Verify correct Cypher generation (no WHERE)
    args, _ = mock_session.__aenter__.return_value.run.call_args
    assert "MATCH (n:Customer)  RETURN properties(n) as p" in args[0]

    # 2. Test WITH WHERE clause
    mock_session.__aenter__.return_value.run.return_value = AsyncIterator(mock_records)

    await connector.get_all("Customer", where_clause="WHERE n.id > 10")

    # Verify Cypher generation (with WHERE)
    args, _ = mock_session.__aenter__.return_value.run.call_args
    assert "MATCH (n:Customer) WHERE n.id > 10 RETURN properties(n) as p" in args[0]


@pytest.mark.asyncio
async def test_spark_dependencies_missing(connector):
    """
    Targets: RuntimeError when Spark is unavailable (Image 2 & 4).
    """
    ast = parse_one("SELECT * FROM table")

    with patch("polyfuseql.connector.Neo4j.get_spark_session", return_value=None):
        with pytest.raises(RuntimeError, match="PySpark is not available"):
            await connector.join(ast)
        with pytest.raises(RuntimeError, match="PySpark is required"):
            await connector.group_by(ast)
        with pytest.raises(RuntimeError, match="PySpark is required"):
            await connector.aggregate(ast)


def test_process_row_validation_logic(connector):
    """
    Targets: _process_row_for_neo4j edge cases (Image 5, Lines 436, 451).
    """
    cols = ["id", "name"]

    # Case 1: Empty/Short line (Lines 436)
    assert connector._process_row_for_neo4j([], cols, MockModel) is None
    assert connector._process_row_for_neo4j(["1"], cols, MockModel) is None

    # Case 2: ValidationError (Lines 451)
    # Passing "invalid" for an integer field 'id' triggers validation error
    bad_row = ["invalid", "name"]
    result = connector._process_row_for_neo4j(bad_row, cols, MockModel)
    assert result is None


@pytest.mark.asyncio
async def test_spark_logic_flow(connector):
    """
    Targets: Spark logic inside join/group_by (Image 2 & 4).
    Mocks the Spark chain to execute the logic without a real Spark context.
    """
    # Mock Spark entities
    mock_spark = MagicMock()
    mock_df = MagicMock()

    # Setup fluent interface mocking (df.filter().select()...)
    for method in [
        "alias",
        "join",
        "filter",
        "select",
        "orderBy",
        "limit",
        "groupBy",
        "agg",
    ]:
        getattr(mock_df, method).return_value = mock_df

    # Setup data return
    mock_row = MagicMock()
    mock_row.asDict.return_value = {"col": "val"}
    mock_df.collect.return_value = [mock_row]
    mock_df.isEmpty.return_value = False

    # Patch dependencies
    with patch(
        "polyfuseql.connector.Neo4j.get_spark_session", return_value=mock_spark
    ), patch.object(
        connector, "_load_table_to_spark_df", return_value=mock_df
    ), patch.object(
        connector, "_translate_expression_to_spark", return_value=MagicMock()
    ):

        # Test JOIN flow
        join_ast = parse_one("SELECT * FROM t1 JOIN t2 ON t1.id=t2.id WHERE t1.a > 5")
        await connector.join(join_ast)
        assert mock_df.join.called
        assert mock_df.filter.called

        # Test GROUP BY flow
        group_ast = parse_one("SELECT a, count(*) FROM t1 GROUP BY a ORDER BY a")
        await connector.group_by(group_ast)
        assert mock_df.groupBy.called
        assert mock_df.agg.called
        assert mock_df.orderBy.called

        # Test AGGREGATE flow
        agg_ast = parse_one("SELECT count(*) FROM t1")
        await connector.aggregate(agg_ast)
        assert mock_df.agg.called
