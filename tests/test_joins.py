import pytest
from polyfuseql.client.PolyClient import PolyClient
import uuid


@pytest.mark.asyncio
async def test_native_postgres_join():
    """Tests a native JOIN on two tables within PostgreSQL."""
    async with PolyClient() as client:
        sql = """
              SELECT o."order_id", p."product_name"
              FROM "orders" AS o
              JOIN "order_details" AS od ON o."order_id" = od."order_id"
              JOIN "products" AS p ON od."product_id" = p."product_id"
              WHERE o."order_id" = 10251 \
              """
        results = await client.execute(sql, engine="postgres")
        assert len(results) == 3
        product_names = {row["productName"] for row in results}
        assert "Ravioli Angelo" in product_names


@pytest.mark.asyncio
async def test_neo4j_join():
    """Tests a SQL JOIN translated to a Cypher query in Neo4j."""
    async with PolyClient() as client:
        # This query finds orders by a customer
        # and joins to get the customer's name
        sql = """
              SELECT o.orderID, c.companyName
              FROM Order o
                       JOIN Customer c ON o.customerID = c.customerID
              WHERE o.orderID = 10308 \
              """
        results = await client.execute(sql, engine="neo4j")
        assert len(results) >= 1
        assert results[0]["orderID"] == 10308
        expected_company_name = "Ana Trujillo Emparedados y helados"
        assert results[0]["companyName"] == expected_company_name


@pytest.mark.asyncio
async def test_redis_application_side_join():
    """Tests an application-side JOIN between two Redis namespaces."""
    async with PolyClient(options={"pk": "id"}) as client:
        # Arrange: Insert data into two separate "tables" (namespaces) in Redis
        user_id = str(uuid.uuid4())
        user_payload = {"id": user_id, "name": "John Doe"}
        profile_payload = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "skill": "Python",
        }

        await client.insert("user", user_payload)
        await client.insert("profile", profile_payload)

        # Act: Perform the JOIN
        sql = "SELECT user.name, profile.skill FROM user "
        sql += "JOIN profile ON user.id = profile.user_id"
        results = await client.execute(sql, engine="redis")

        # Assert
        assert len(results) == 1
        assert results[0]["name"] == "John Doe"
        assert results[0]["skill"] == "Python"
