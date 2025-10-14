import asyncio
import aiohttp
import json

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

# The simple SQL query to execute after successful authentication.
TEST_SQL_QUERY = "SELECT * FROM test_integration_users LIMIT 1"
TEST_KEYSPACE = "mykeyspace"


async def run_test():
    """
    Runs a two-stage isolated test:
    1. Authenticates with the auth service.
    2. Uses the received token to execute a query via the translator service.
    """
    print("--- Starting Isolated Cassandra Connection Test ---")
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

                if response.status == 201 or response.status == 200:
                    print("-> Authentication successful!")
                    response_json = json.loads(response_text)
                    jwt_token = response_json.get("accessToken")
                    if jwt_token:
                        print("-> Successfully extracted JWT token.")
                    else:
                        print(
                            "-> ERROR: 'accessToken' not found in response payload:"  # noqa:E501
                        )  # noqa:E501
                        print(response_json)
                        return
                else:
                    print("-> ERROR: Authentication failed. Response body:")
                    try:
                        # Try to pretty-print if it's JSON,
                        # otherwise print as text.
                        print(json.dumps(json.loads(response_text), indent=2))
                    except json.JSONDecodeError:
                        print(response_text)
                    return  # Stop the test if authentication fails

        except aiohttp.ClientConnectorError as e:
            print(
                "\n[FATAL ERROR] Connection failed. Is the auth service running at http://localhost:3001?"  # noqa:E501
            )
            print(f"Details: {e}")
            return
        except Exception as e:
            print(
                f"\n[FATAL ERROR] An unexpected error occurred during authentication: {e}"  # noqa:E501
            )
            return

        # --- Step 2: Execute a query using the JWT ---
        if not jwt_token:
            print("\n--- Test Aborted: No JWT token was obtained. ---")
            return

        print(
            f"\n[Step 2] Attempting to execute query at: {TRANSLATOR_SERVICE_URL}"  # noqa:E501
        )  # noqa:E501
        headers = {"Authorization": f"Bearer {jwt_token}"}
        payload = {"sql": TEST_SQL_QUERY, "keyspace": TEST_KEYSPACE}

        try:
            async with session.post(
                TRANSLATOR_SERVICE_URL,
                headers=headers,
                json=payload,
                timeout=20,  # noqa:E501
            ) as response:
                print(
                    f"-> Translator Service Response Status: {response.status}"
                )  # noqa:E501
                response_text = await response.text()

                if response.status == 201 or response.status == 200:
                    print("-> Query execution successful!")
                    print("-> Response Body:")
                    print(json.dumps(json.loads(response_text), indent=2))
                else:
                    print("-> ERROR: Query execution failed. Response body:")
                    try:
                        print(json.dumps(json.loads(response_text), indent=2))
                    except json.JSONDecodeError:
                        print(response_text)

        except aiohttp.ClientConnectorError as e:
            print(
                "\n[FATAL ERROR] Connection failed. Is the translator service running at http://localhost:3101?"  # noqa:E501
            )
            print(f"Details: {e}")
            return
        except Exception as e:
            print(
                f"\n[FATAL ERROR] An unexpected error occurred during query execution: {e}"  # noqa:E501
            )
            return

    print("\n--- Test Finished ---")


if __name__ == "__main__":
    # Ensure you have the microservices running before executing this script.
    # To run: python test_isolated_cassandra_connection.py
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
