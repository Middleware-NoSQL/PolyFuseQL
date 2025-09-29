# tests/test_query_product.py
import pytest
import uuid
from polyfuseql.client.PolyClient import PolyClient


@pytest.fixture
async def product_in_db():
    """
    A pytest fixture that creates the necessary schema, inserts a product
    and its dependencies using parameterized queries, runs the test, and
    then cleans everything up.
    """
    client = PolyClient()
    await client.__aenter__()

    # --- SETUP: Define Schema and Data ---
    supplier_id = 999
    category_id = 999
    product_id = 99999
    product_name = f"Test Product {uuid.uuid4()}"

    # SQL statements to create tables if they don't exist.
    create_category_sql = """
    CREATE TABLE IF NOT EXISTS "Category" (
        "categoryID"   INTEGER     NOT NULL PRIMARY KEY,
        "categoryName" VARCHAR(15) NOT NULL,
        "description"  TEXT,
        "picture"      BYTEA
    );
    """
    create_supplier_sql = """
    CREATE TABLE IF NOT EXISTS "Supplier" (
        "supplierID"   INTEGER     NOT NULL PRIMARY KEY,
        "companyName"  VARCHAR(40) NOT NULL,
        "contactName"  VARCHAR(30),
        "contactTitle" VARCHAR(30),
        "address"      VARCHAR(60),
        "city"         VARCHAR(15),
        "region"       VARCHAR(15),
        "postalCode"   VARCHAR(10),
        "country"      VARCHAR(15),
        "phone"        VARCHAR(24),
        "fax"          VARCHAR(24),
        "homePage"     TEXT
    );
    """
    create_product_sql = """
    CREATE TABLE IF NOT EXISTS "Product" (
        "productID"       INTEGER       NOT NULL PRIMARY KEY,
        "productName"     VARCHAR(60)   NOT NULL,
        "supplierID"      INTEGER       REFERENCES "Supplier"("supplierID"),
        "categoryID"      INTEGER       REFERENCES "Category"("categoryID"),
        "quantityPerUnit" VARCHAR(20),
        "unitPrice"       REAL,
        "unitsInStock"    SMALLINT,
        "unitsOnOrder"    SMALLINT,
        "reorderLevel"    SMALLINT,
        "discontinued"    INTEGER       NOT NULL
    );
    """

    try:
        # --- SETUP: Execute Schema and Data Creation ---
        await client.pg.query(create_category_sql)
        await client.pg.query(create_supplier_sql)
        await client.pg.query(create_product_sql)

        # Use parameterized queries for inserts
        supplier_sql = 'INSERT INTO "Supplier" ("supplierID", "companyName") VALUES ($1, $2)'  # noqa
        await client.pg.query(supplier_sql, (supplier_id, "Test Supplier Inc."))  # noqa

        category_sql = 'INSERT INTO "Category" ("categoryID", "categoryName") VALUES ($1, $2)'  # noqa
        await client.pg.query(category_sql, (category_id, "Test Category"))

        product_data = {
            "productID": product_id,
            "productName": product_name,
            "supplierID": supplier_id,
            "categoryID": category_id,
            "quantityPerUnit": "1 test unit",
            "unitPrice": 25.50,
            "unitsInStock": 100,
            "unitsOnOrder": 0,
            "reorderLevel": 10,
            "discontinued": 0,
        }

        # Construct parameterized INSERT for the product
        columns = ", ".join(f'"{k}"' for k in product_data.keys())
        placeholders = ", ".join(f"${i+1}" for i in range(len(product_data)))
        values = tuple(product_data.values())
        insert_sql = (
            f'INSERT INTO "Product" ({columns}) VALUES ({placeholders})'  # noqa
        )
        await client.pg.query(insert_sql, values)

        yield client, product_data

    finally:
        # --- TEARDOWN ---
        # Clean up by dropping the tables in reverse order of dependency
        # using CASCADE.
        try:
            await client.pg.query('DROP TABLE IF EXISTS "Product" CASCADE;')
            await client.pg.query('DROP TABLE IF EXISTS "Supplier" CASCADE;')
            await client.pg.query('DROP TABLE IF EXISTS "Category" CASCADE;')
        except Exception as e:
            print(f"Error during test cleanup: {e}")
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_query_product_postgres(product_in_db):
    """
    Tests querying a product from PostgreSQL.
    This test now uses a fully self-contained fixture that handles
    schema creation.
    """
    client, product_data = product_in_db
    product_id_to_query = product_data["productID"]
    expected_product_name = product_data["productName"]

    # Act: Execute the SELECT query
    rows = await client.execute(
        f'SELECT * FROM "Product" WHERE "productID" = {product_id_to_query}',  # noqa
        engine="postgres",
        use_catalogue=False,
    )

    # Assert: Verify that the correct data was returned
    assert rows, "Query should return the product we just inserted."
    assert len(rows) == 1, "Query should return exactly one product."
    assert rows[0]["productName"] == expected_product_name
