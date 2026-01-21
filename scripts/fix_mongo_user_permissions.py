import asyncio
from pymongo import AsyncMongoClient
import logging
import sys

# We use simple string for password if hashing lib not available,
# assuming API handles plain text or we match the hashing algo.
# For standard Flask-Security/Werkzeug:
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    # Fallback to plain text if werkzeug not installed in test env
    # (The middleware likely hashes it on receipt or comparison)
    logging.warning("werkzeug not found. Using plain text password.")

    def generate_password_hash(p):
        return p


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout
)

# MongoDB Configuration (Native connection)
# This connects to the MongoDB container mapped to port 27018
MONGO_URI = "mongodb://root:example@localhost:27018/"
AUTH_DB_NAME = "sql_middleware_auth"
USERS_COLLECTION = "users"


async def fix_permissions():
    logging.info(f"Connecting to MongoDB at {MONGO_URI}...")
    client = AsyncMongoClient(MONGO_URI)

    try:
        # Check connection
        await client.admin.command("ping")
        logging.info("Connected to MongoDB.")

        db = client[AUTH_DB_NAME]
        users = db[USERS_COLLECTION]

        # User details
        username = "admin"
        password = "admin123"

        # [CRITICAL FIX] Permissions must be a Dictionary (Map), not a List.
        # The API calls .get('SELECT', False) on this object.
        permissions = {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": True,
            "DELETE": True,
            "ALL": True,
            # Add lowercase variants just in case
            "select": True,
            "insert": True,
            "update": True,
            "delete": True,
            "read": True,
            "write": True,
        }

        user_doc = {
            "username": username,
            "password": generate_password_hash(password),
            "role": "admin",
            "is_admin": True,
            "permissions": permissions,
            "is_active": True,
        }

        # Update or Insert
        logging.info(
            f"Upserting user '{username}' into '{AUTH_DB_NAME}.{USERS_COLLECTION}'..."
        )
        result = await users.update_one(
            {"username": username}, {"$set": user_doc}, upsert=True
        )

        if result.upserted_id:
            logging.info(f"User created with ID: {result.upserted_id}")
        else:
            logging.info("User updated.")

        # Verify
        saved = await users.find_one({"username": username})
        logging.info(f"Current User State in DB: {saved}")

    except Exception as e:
        logging.error(f"Failed to update permissions: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(fix_permissions())
