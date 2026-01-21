import asyncio
import aiohttp
import logging
import sys
import json
import time
import base64
import hmac
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# Configuration
BASE_URL = "http://localhost:5101"
JWT_SECRET_KEY = "dev-secret"

# Credentials candidates
CREDS_LIST = [
    {"username": "admin", "password": "admin123"},
    {"username": "root", "password": "example"},
    {"username": "user", "password": "password"},
    {"username": "admin", "password": "password"},
]


def mint_jwt(identity="admin", secret=JWT_SECRET_KEY):
    """
    Manually creates a valid HS256 JWT using the server's secret.
    Includes CORRECT permissions structure (Dictionary) to pass RBAC checks.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())

    # [FIX] Permissions MUST be a Dictionary for the API to use .get()
    permissions_dict = {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": True,
        "DELETE": True,
        "ALL": True,
        "select": True,
        "insert": True,
    }

    payload = {
        "fresh": False,
        "iat": now,
        "jti": f"manual-test-token-{now}",
        "type": "access",
        "sub": identity,
        "nbf": now,
        "exp": now + 3600,
        "permissions": permissions_dict,  # Correct format
        "role": "admin",
        "is_admin": True,
    }

    def b64url(data):
        json_bytes = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(json_bytes).decode().rstrip("=")

    segments = [b64url(header), b64url(payload)]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    segments.append(base64.urlsafe_b64encode(signature).decode().rstrip("="))
    return ".".join(segments)


async def probe_endpoint(session, method, path, payload=None, headers=None):
    url = f"{BASE_URL}{path}"
    try:
        logging.info(f"--- Probing {method} {path} ---")
        logging.info(f"Payload: {json.dumps(payload)}")

        async with session.request(method, url, json=payload, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"Status: {resp.status}")
            logging.info(f"Response Body: {text[:500]}")
            return resp.status

    except Exception as e:
        logging.error(f"Failed to connect to {url}: {e}")
        return 0


async def main():
    logging.info(f"Starting connection diagnostics for {BASE_URL}...")

    async with aiohttp.ClientSession() as session:
        # 1. Health Check
        await probe_endpoint(session, "GET", "/health")

        # 2. Token Fuzzing with CORRECT permissions structure
        logging.info("\n=== TESTING TOKEN WITH PERMISSIONS DICT ===")

        identity = "admin"
        token = mint_jwt(identity)
        headers = {"Authorization": f"Bearer {token}"}

        # Test SELECT (Read)
        logging.info(">>> Attempting SELECT Query...")
        payload_select = {
            "query": "SELECT * FROM nation LIMIT 1",
            "database": "tpch",
            "collection": "nation",
        }
        await probe_endpoint(session, "POST", "/translate", payload_select, headers)

        # Test INSERT (Write)
        logging.info(">>> Attempting INSERT Query...")
        payload_insert = {
            "query": "INSERT INTO nation (n_nationkey, n_name) VALUES (999, 'TEST')",
            "database": "tpch",
            "collection": "nation",
        }
        await probe_endpoint(session, "POST", "/translate", payload_insert, headers)


if __name__ == "__main__":
    asyncio.run(main())
