import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from aiohttp import ClientResponseError, RequestInfo
from polyfuseql.connector.Cassandra import CassandraConnector
from polyfuseql.config import settings


@pytest.fixture
def cassandra_connector():
    return CassandraConnector(settings=settings)


# --- Connection & Auth Tests ---


@pytest.mark.asyncio
async def test_ping_not_connected(cassandra_connector):
    """
    Targets: ping() raising ConnectionError when session is None.
    """
    cassandra_connector._http_session = None
    with pytest.raises(ConnectionError, match="Cannot ping, session not connected"):
        await cassandra_connector.ping()


@pytest.mark.asyncio
async def test_ping_failure(cassandra_connector):
    """
    Targets: ping() returning False on exception.
    """
    # Mock session to exist but raise error on get()
    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("Network Down")
    cassandra_connector._http_session = mock_session

    result = await cassandra_connector.ping()
    assert result is False


@pytest.mark.asyncio
async def test_connect_auth_failure_client_error(cassandra_connector):
    """
    Targets: _authenticate_with_translator catching aiohttp.ClientError.
    """
    with patch(
        "aiohttp.ClientSession.post", side_effect=Exception("Auth Service Down")
    ):
        with pytest.raises(Exception, match="Auth Service Down"):
            await cassandra_connector.connect()


@pytest.mark.asyncio
async def test_connect_auth_success_no_token(cassandra_connector):
    """
    Targets: Authentication successful but 'accessToken' missing in response.
    """
    # Mock successful response but empty body
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {}  # No accessToken

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(ConnectionError, match="no access token received"):
            await cassandra_connector.connect()


# --- Execution Logic Tests ---


@pytest.mark.asyncio
async def test_execute_no_session_or_token(cassandra_connector):
    """
    Targets: _execute_via_translator checks for session and token.
    """
    cassandra_connector._http_session = None
    with pytest.raises(ConnectionError, match="HTTP session not initialized"):
        await cassandra_connector._execute_via_translator("SELECT 1")

    cassandra_connector._http_session = MagicMock()
    cassandra_connector._translator_auth_token = None
    with pytest.raises(ConnectionError, match="Not authenticated"):
        await cassandra_connector._execute_via_translator("SELECT 1")


@pytest.mark.asyncio
async def test_execute_translator_api_failure(cassandra_connector):
    """
    Targets: Translator API returning success=False in body.
    """
    cassandra_connector._http_session = MagicMock()
    cassandra_connector._translator_auth_token = "fake-token"

    mock_response = AsyncMock()
    mock_response.json.return_value = {"success": False, "message": "Syntax Error"}

    # Patch the session.post context manager
    cassandra_connector._http_session.post.return_value.__aenter__.return_value = (
        mock_response
    )

    with pytest.raises(ConnectionError, match="Translator API indicated failure"):
        await cassandra_connector.query("SELECT * FROM table")


@pytest.mark.asyncio
async def test_execute_cassandra_execution_failure(cassandra_connector):
    """
    Targets: Translator API success=True, but executionResult.success=False.
    """
    cassandra_connector._http_session = MagicMock()
    cassandra_connector._translator_auth_token = "fake-token"

    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "success": True,
        "executionResult": {"success": False, "message": "Timeout during read"},
    }
    cassandra_connector._http_session.post.return_value.__aenter__.return_value = (
        mock_response
    )

    with pytest.raises(ConnectionError, match="Cassandra execution failed"):
        await cassandra_connector.query("SELECT * FROM table")


@pytest.mark.asyncio
async def test_execute_http_error(cassandra_connector):
    """
    Targets: aiohttp raising ClientResponseError during query.
    """
    cassandra_connector._http_session = MagicMock()
    cassandra_connector._translator_auth_token = "fake-token"

    # Create a proper ClientResponseError mock
    req_info = RequestInfo(url="http://test", method="POST", headers={})
    error = ClientResponseError(
        req_info, history=(), status=500, message="Internal Error"
    )

    cassandra_connector._http_session.post.side_effect = error

    with pytest.raises(ConnectionError, match="Failed to communicate"):
        await cassandra_connector.query("SELECT 1")


# --- Helper & Bulk Load Tests ---


def test_format_value(cassandra_connector):
    """
    Targets: _format_value edge cases (None, int, string escaping).
    """
    assert cassandra_connector._format_value(None) == "NULL"
    assert cassandra_connector._format_value(123) == "123"
    assert cassandra_connector._format_value("O'Reilly") == "'O''Reilly'"
    assert cassandra_connector._format_value(True) == "True"


@pytest.mark.asyncio
async def test_bulk_insert_file_not_found(cassandra_connector):
    """
    Targets: bulk_insert FileNotFoundError exception handler.
    """
    # Should catch exception and log error, returning 0
    count = await cassandra_connector.bulk_insert("table", "non_existent_file.csv")
    assert count == 0


@pytest.mark.asyncio
async def test_count_method_parsing(cassandra_connector):
    """
    Targets: count() parsing logic for the specific list response format.
    """
    # FIX: Mock _execute_via_translator because count() calls it directly,
    # not via query().
    # Mocking query() left _execute_via_translator exposed, which triggered the
    # ConnectionError because we are not connected.
    with patch.object(
        cassandra_connector, "_execute_via_translator", new_callable=AsyncMock
    ) as mock_exec:
        # Case 1: Valid response [{'count': '42'}]
        mock_exec.return_value = [{"count": "42"}]

        result = await cassandra_connector.count("Users")
        assert result == 42

        # Case 2: Empty result fallback
        mock_exec.return_value = []
        assert await cassandra_connector.count("Users") == 0
