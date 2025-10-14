# tests/test_api.py
"""
Integration tests for the API endpoints.
NOTE: These tests require the full Docker Compose stack to be running.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from polyfuseql.app.main import app


@pytest.mark.asyncio
async def test_read_root():
    """
    Test the root endpoint.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the PolyFuseQL API!"}


@pytest.mark.asyncio
async def test_query_postgres():
    """
    Test the PostgreSQL query endpoint against a live database.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/postgres/query", json={"sql": "SELECT 1 AS test_col;"}
        )

    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert data["result"] == [{"test_col": 1}]


@pytest.mark.asyncio
async def test_query_redis():
    """
    Test the Redis query endpoint against a live database.
    This assumes data has been loaded into Redis.
    """
    # This query is based on the TPC-H schema and
    # tests the SQL parsing for Redis.
    sql_query = "SELECT * FROM Customer WHERE c_custkey = '1'"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/redis/query", json={"sql": sql_query})

    assert response.status_code == 200
    assert "result" in response.json()


@pytest.mark.asyncio
async def test_query_neo4j():
    """
    Test the Neo4j query endpoint against a live database.
    """
    # Using a simple Cypher query that PolyFuseQL's core can handle.
    sql_query = "MATCH (n) RETURN count(n) AS node_count"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/neo4j/query", json={"sql": sql_query})

    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    # The result should be a list with a single dictionary,
    # e.g., [{'node_count': 123}]
    assert "node_count" in data["result"][0]


@pytest.mark.asyncio
async def test_query_cassandra():
    """
    Test the Cassandra query endpoint against a live database and translator.
    """
    # This is a basic query that should always work on a
    # live Cassandra instance.
    sql_query = "SELECT cluster_name FROM system.local"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/cassandra/query", json={"sql": sql_query})

    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "cluster_name" in data["result"][0]


@pytest.mark.asyncio
async def test_query_mongodb():
    """
    Test the MongoDB query endpoint against a live database and translator.
    """
    # This requires a 'customer' collection in the MongoDB test database.
    sql_query = "SELECT * FROM customer LIMIT 1"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post("/mongodb/query", json={"sql": sql_query})

    assert response.status_code == 200
    assert "result" in response.json()
