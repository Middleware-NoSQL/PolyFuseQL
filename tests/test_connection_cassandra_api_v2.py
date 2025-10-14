import asyncio
import aiohttp
import json
import uuid

# --- Configuration ---
# These URLs should match the running microservices.
AUTH_SERVICE_URL = "http://localhost:3001/api/auth/login"
TRANSLATOR_SERVICE_URL = "http://localhost:3101/api/translator/execute"

# --- FIX: Added the 'nombre' field to the credentials payload. ---
# The auth service's validation requires this field for the login request,
# as indicated by the "El nombre es requerido" error message.
CREDENTIALS = {
    "cedula": "admin",
    "nombre": "Admin User",
    "contrasena": "admin123",
}  # noqa:E501

# --- Test Constants ---
TEST_KEYSPACE = "mykeyspace"
TEST_TABLE = "test_integration_users"


async def execute_query(
    session: aiohttp.ClientSession,
    token: str,
    sql: str,
    keyspace: str = TEST_KEYSPACE,  # noqa:E501
):
    """
    Sends a single SQL query to the translator service
    and prints the full response.

    Args:
        session: The active aiohttp.ClientSession.
        token: The JWT authorization token.
        sql: The SQL query string to execute.
        keyspace: The Cassandra keyspace to target.
    """
    print("\n" + "=" * 80)
    print("EXECUTING QUERY:")
    print(f"  SQL: {sql}")
    print(f"  KEYSPACE: {keyspace}")
    print("=" * 80)

    if not token:
        print("[FATAL ERROR] Cannot execute query without a JWT token.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    payload = {"sql": sql, "keyspace": keyspace}

    try:
        async with session.post(
            TRANSLATOR_SERVICE_URL, headers=headers, json=payload, timeout=20
        ) as response:
            print(f"-> Translator Service Response Status: {response.status}")
            response_text = await response.text()

            print("-> Full Response Body:")
            try:
                # Try to pretty-print if it's JSON, otherwise print as text.
                print(json.dumps(json.loads(response_text), indent=2))
            except json.JSONDecodeError:
                print(response_text)

    except aiohttp.ClientConnectorError as e:
        print(
            "\n[FATAL ERROR] Connection failed. Is the translator service running at http://localhost:3101?"  # noqa:E501
        )
        print(f"Details: {e}")
    except Exception as e:
        print(
            f"\n[FATAL ERROR] An unexpected error occurred during query execution: {e}"  # noqa:E501
        )


async def run_test():
    """
    Runs a multi-stage diagnostic test that mirrors
    the pytest integration suite.
    1. Authenticates with the auth service.
    2. Executes all queries from the integration tests via
    the translator service.
    """
    print("--- Starting Isolated Cassandra Diagnostic Script ---")
    jwt_token = None
    async with aiohttp.ClientSession() as session:
        # --- Step 1: Authenticate and get JWT ---
        print(f"\n[Step 1] Attempting to authenticate at: {AUTH_SERVICE_URL}")
        try:
            async with session.post(
                AUTH_SERVICE_URL, json=CREDENTIALS, timeout=10
            ) as response:
                print(f"-> Auth Service Response Status: {response.status}")
                response_text = await response.text()

                if 200 <= response.status < 300:
                    print("-> Authentication successful!")
                    response_json = json.loads(response_text)
                    jwt_token = response_json.get("accessToken")
                    if not jwt_token:
                        print(
                            "-> ERROR: 'accessToken' not found in response payload:"  # noqa:E501
                        )  # noqa:E501
                        print(response_json)
                        return
                    print("-> Successfully extracted JWT token.")
                else:
                    print("-> ERROR: Authentication failed. Response body:")
                    try:
                        print(json.dumps(json.loads(response_text), indent=2))
                    except json.JSONDecodeError:
                        print(response_text)
                    return
        except aiohttp.ClientConnectorError as e:
            print(
                f"\n[FATAL ERROR] Connection failed. Is the auth service running at {AUTH_SERVICE_URL}?"  # noqa:E501
            )
            print(f"Details: {e}")
            return
        except Exception as e:
            print(
                f"\n[FATAL ERROR] An unexpected error occurred during authentication: {e}"  # noqa:E501
            )
            return

        if not jwt_token:
            print("\n--- Test Aborted: No JWT token was obtained. ---")
            return

        # --- Step 2: Replicate Pytest Execution Flow ---
        print("\n\n--- [PHASE 1] Replicating Schema Setup ---")
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {TEST_KEYSPACE}.{TEST_TABLE} (
            user_id int PRIMARY KEY,
            name text,
            email text,
            age int
        )
        """
        await execute_query(session, jwt_token, create_table_sql)

        # --- Test: `test_cassandra_crud_operations` ---
        print(
            "\n\n--- [PHASE 2] Replicating 'test_cassandra_crud_operations' ---"  # noqa:E501
        )  # noqa:E501
        user_id_crud = int(str(uuid.uuid4().int)[:5])
        original_name = "Cassandra User"
        updated_name = "Updated Cassandra User"
        await execute_query(session, jwt_token, f"TRUNCATE TABLE {TEST_TABLE}")

        # 1. Insert
        insert_sql = f"INSERT INTO {TEST_TABLE} (user_id, name, email, age) VALUES ({user_id_crud}, '{original_name}', 'crud@example.com', 40)"  # noqa:E501
        await execute_query(session, jwt_token, insert_sql)

        # 2. Get (Verify Insert)
        await execute_query(
            session,
            jwt_token,
            f"SELECT * FROM {TEST_TABLE} WHERE user_id = {user_id_crud}",
        )

        # 3. Update
        update_sql = f"UPDATE {TEST_TABLE} SET name = '{updated_name}' WHERE user_id = {user_id_crud}"  # noqa:E501
        await execute_query(session, jwt_token, update_sql)

        # 4. Get (Verify Update)
        await execute_query(
            session,
            jwt_token,
            f"SELECT * FROM {TEST_TABLE} WHERE user_id = {user_id_crud}",
        )

        # 5. Delete
        delete_sql = f"DELETE FROM {TEST_TABLE} WHERE user_id = {user_id_crud}"
        await execute_query(session, jwt_token, delete_sql)

        # 6. Get (Verify Delete)
        await execute_query(
            session,
            jwt_token,
            f"SELECT * FROM {TEST_TABLE} WHERE user_id = {user_id_crud}",
        )

        # --- Test: `test_cassandra_get_all_and_count` ---
        print(
            "\n\n--- [PHASE 3] Replicating 'test_cassandra_get_all_and_count' ---"  # noqa:E501
        )  # noqa:E501
        user_id_1 = int(str(uuid.uuid4().int)[:5])
        user_id_2 = int(str(uuid.uuid4().int)[:6])
        await execute_query(session, jwt_token, f"TRUNCATE TABLE {TEST_TABLE}")
        await execute_query(
            session,
            jwt_token,
            f"INSERT INTO {TEST_TABLE} (user_id, name, age) VALUES ({user_id_1}, 'User A', 30)",  # noqa:E501
        )
        await execute_query(
            session,
            jwt_token,
            f"INSERT INTO {TEST_TABLE} (user_id, name, age) VALUES ({user_id_2}, 'User B', 35)",  # noqa:E501
        )

        # Get All
        await execute_query(session, jwt_token, f"SELECT * FROM {TEST_TABLE}")

        # Count
        await execute_query(
            session, jwt_token, f"SELECT COUNT(*) FROM {TEST_TABLE}"
        )  # noqa:E501

        # --- Test: `test_cassandra_complex_query` ---
        print(
            "\n\n--- [PHASE 4] Replicating 'test_cassandra_complex_query' ---"
        )  # noqa:E501
        user_id_filter = int(str(uuid.uuid4().int)[:7])
        await execute_query(session, jwt_token, f"TRUNCATE TABLE {TEST_TABLE}")
        await execute_query(
            session,
            jwt_token,
            f"INSERT INTO {TEST_TABLE} (user_id, name, age, email) VALUES ({user_id_filter}, 'FilterUser', 55, 'filter@example.com')",  # noqa:E501
        )

        # Complex Select (Note: Cassandra requires `ALLOW FILTERING`
        # for non-primary key WHERE clauses)
        complex_sql = f"SELECT name, email FROM {TEST_TABLE} WHERE age > 50"
        await execute_query(session, jwt_token, complex_sql)

    print("\n--- Diagnostic Script Finished ---")


if __name__ == "__main__":
    # Ensure you have the microservices running before executing this script.
    # To run: python test_isolated_cassandra_connection.py
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
