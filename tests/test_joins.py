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
        print("test_native_postgres_join_results", results)
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
              WHERE o.orderID = '10248' \
              """
        results = await client.execute(sql, engine="neo4j")
        assert len(results) >= 1
        print("test-neo4j-join_results[0]", results[0])
        assert results[0]["orderID"] == "10248"
        expected_company_name = "Vins et alcools Chevalier"
        assert results[0]["companyName"] == expected_company_name


@pytest.mark.asyncio
async def test_redis_application_side_join():
    """Tests an application-side JOIN between two Redis namespaces."""
    async with PolyClient(options={"data_type": "string"}) as client:
        # Arrange: Insert data into two separate "tables" (namespaces) in Redis
        user_id = str(uuid.uuid4())[:4]
        user_payload = {"id": user_id, "name": "John Doe"}
        profile_payload = {
            "id": str(uuid.uuid4())[:4],
            "user_id": user_id,
            "skill": "Python",
        }
        sql = "INSERT INTO User(id, name) "
        sql += f"VALUES ('{user_payload.get("id")}', "
        sql += f"'{user_payload.get("name")}')"

        result = await client.execute(sql, engine="redis")
        print("test-joins-result_insert_user", result)
        sql = "INSERT INTO Profile(id, user_id, skill) "
        sql += f"VALUES ('{profile_payload.get("id")}', "
        sql += f"'{profile_payload.get("user_id")}', "
        sql += f"'{profile_payload.get("skill")}')"

        result = await client.execute(sql, engine="redis")
        print("test-joins-result_insert_profile", result)
        # await client.insert("user", user_payload)
        # await client.insert("profile", profile_payload)

        # Act: Perform the JOIN
        sql = "SELECT User.name, Profile.skill FROM User "
        sql += "JOIN Profile ON User.id = Profile.user_id "
        sql += f"WHERE User.id = '{user_id}'"
        print("test-joins-redis_sql", sql)
        results = await client.execute(sql, engine="redis")

        # Assert
        assert len(results) == 1
        assert results[0]["name"] == "John Doe"
        assert results[0]["skill"] == "Python"
