import pymongo
import sys

# --- Connection Details ---
# Constructed from the provided logs.
# MODIFIED: Changed hostname from 'mongodb' to 'localhost' to connect
# from the host machine to the port exposed by Docker.
MONGO_URI = "mongodb://root:example@localhost:27018/"

# --- Create a new client and connect to the server ---
# We'll set a short serverSelectionTimeoutMS (e.g., 5000ms = 5s)
# to ensure the script fails quickly if the server is not reachable.
client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

# --- Test the Connection ---
try:
    # The ping command is a lightweight way to force a connection
    # and verify that authentication was successful.
    client.admin.command("ping")
    print("✅ MongoDB connection successful!")
    print(f"Server Info: {client.server_info()['version']}")

except pymongo.errors.ServerSelectionTimeoutError as err:
    # This error occurs when the driver fails to find a server
    # to send an operation to, often due to DNS or network issues.
    print(
        "❌ Connection Failed: Could not connect to the server. Details below:"
    )  # noqa:E501
    print(err)
    sys.exit(1)  # Exit with an error code

except pymongo.errors.OperationFailure as err:
    # This error typically indicates an authentication failure.
    print(
        "❌ Authentication Failed: Please check your username and password. Details below:"  # noqa:E501
    )  # noqa:E501
    print(f"Error Code: {err.code}, Message: {err.details}")
    sys.exit(1)  # Exit with an error code

finally:
    # --- Clean up the connection ---
    if client:
        client.close()
        print("\nConnection closed.")
