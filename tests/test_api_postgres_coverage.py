import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from polyfuseql.app.main import app

# Base URL for the mocked app environment
BASE_URL = "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_postgres_root_endpoint():
    """
    Targets `read_root` in postgres.py to cover lines 22-23.

    The existing tests hit the main app root ("/"), but not the
    Postgres-specific router root ("/postgres/").
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as ac:
        # Note the trailing slash or prefix depending on how the router is mounted.
        # In app/main.py: prefix="/postgres" -> endpoint "/" becomes "/postgres/"
        response = await ac.get("/postgres/")

    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the Postgres API!"}


@pytest.mark.asyncio
async def test_postgres_query_exception_handling():
    """
    Targets the Exception block in `postgres_query` (lines 39-42).

    We mock the `execute_query` service to raise a generic Exception.
    This forces the API to enter the `except Exception as e:` block,
    triggering the logger and the 500 HTTPException.
    """
    # We patch the function where it is defined in the services module
    with patch(
        "polyfuseql.app.services.services.execute_query",
        side_effect=Exception("Simulated Critical Failure"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=BASE_URL
        ) as ac:
            response = await ac.post(
                "/postgres/query", json={"sql": "SELECT * FROM critical_systems"}
            )

    # Verify we caught the error and returned the expected 500
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Simulated Critical Failure"
