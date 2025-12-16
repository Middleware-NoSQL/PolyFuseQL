import asyncio
import os
import sys


async def check_connection():
    # -------------------------------------------------------------------------
    # CONFIGURATION
    # -------------------------------------------------------------------------
    # We default to 'host.docker.internal' to target the host machine.
    # If testing container-to-container, change this to the other container's
    # name (e.g., 'db').
    DB_HOST = os.getenv("DB_HOST", "postgres")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_USER = os.getenv("DB_USER", "tpch")
    DB_PASS = os.getenv(
        "DB_PASSWORD", "tpch"
    )  # Adjust this if your local password differs
    DB_NAME = os.getenv("DB_NAME", "tpch")

    print("--- Connection Configuration ---")
    print(f"Host: {DB_HOST}")
    print(f"Port: {DB_PORT}")
    print(f"User: {DB_USER}")
    print(f"Database: {DB_NAME}")
    print("--------------------------------")

    try:
        print(
            f"Attempting connection to postgres:"
            f"//{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME} ..."
        )

        # Establish connection
        conn = await asyncpg.connect(
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT,
            timeout=5,  # 5 second timeout
        )

        print("\n✅ SUCCESS: Connected to PostgreSQL!")

        # Simple query to verify
        version = await conn.fetchval("SELECT version()")
        print(f"Server Version: {version}")

        await conn.close()

    except OSError as e:
        print("\n❌ NETWORK ERROR: Could not reach the host.")
        print(f"Details: {e}")
    except asyncpg.InvalidPasswordError:
        print("\n❌ AUTH ERROR: Invalid password or username.")
    except Exception as e:
        print("\n❌ FAILURE: An unexpected error occurred.")
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Check for library availability
    try:
        import asyncpg
    except ImportError:
        print("Error: 'asyncpg' module not found.")
        print("Please run: pip install asyncpg")
        sys.exit(1)

    asyncio.run(check_connection())
