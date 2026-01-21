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
JWT_SECRET_KEY = "dev-secret"  # From docker-compose environment

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
    This bypasses the /auth/login endpoint if credentials aren't seeded in the DB.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "fresh": False,
        "iat": now,
        "jti": "manual-test-token-" + str(now),
        "type": "access",
        "sub": identity,
        "nbf": now,
        "exp": now + 3600,  # 1 hour validity
    }

    def b64url(data):
        # JWT spec requires compact JSON (no spaces)
        json_bytes = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(json_bytes).decode().rstrip("=")

    segments = [b64url(header), b64url(payload)]
    signing_input = ".".join(segments).encode()

    # Sign with HMAC-SHA256 using the shared secret
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    segments.append(base64.urlsafe_b64encode(signature).decode().rstrip("="))

    return ".".join(segments)


async def probe_endpoint(
    session, method, path, payload=None, headers=None, expect_status=200
):
    url = f"{BASE_URL}{path}"
    try:
        logging.info(f"--- Probing {method} {path} ---")
        if method == "POST":
            async with session.post(url, json=payload, headers=headers) as resp:
                text = await resp.text()
                logging.info(f"Status: {resp.status}")
                logging.info(f"Response: {text[:300]}...")
                return resp.status == expect_status
        elif method == "GET":
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                logging.info(f"Status: {resp.status}")
                return resp.status == expect_status
    except Exception as e:
        logging.error(f"Failed to connect to {url}: {e}")
        return False


async def main():
    logging.info(f"Starting connection diagnostics for {BASE_URL}...")

    async with aiohttp.ClientSession() as session:
        # 1. Health Check
        await probe_endpoint(session, "GET", "/health")

        # 2. Auth Probe (Try standard login first)
        token = None
        auth_path = "/api/auth/login"

        logging.info("Attempting standard login...")
        for creds in CREDS_LIST:
            try:
                async with session.post(f"{BASE_URL}{auth_path}", json=creds) as resp:
                    if resp.status == 200:
                        data = json.loads(await resp.text())
                        token = data.get("access_token")
                        if token:
                            logging.info(
                                f"✅ Login Successful with {creds['username']}"
                            )
                            break
            except:
                pass

        # 3. Auth Bypass (Mint Token)
        if not token:
            logging.warning(
                f"⚠️ Standard login failed. Attempting to MINT token using secret '{JWT_SECRET_KEY}'..."
            )
            try:
                token = mint_jwt("admin")
                logging.info(f"✅ Minted manual token: {token[:20]}...")
            except Exception as e:
                logging.error(f"Failed to mint token: {e}")

        if not token:
            logging.error("❌ No token available. Aborting query tests.")
            return

        # 4. Query Probe
        # The previous error "No se pudo determinar el nombre de la colección" implies we missed a field.
        query_payload = {
            "query": "SELECT * FROM nation LIMIT 1",
            "database": "tpch",
            "collection": "nation",
            # [FIX] Added collection field required by translator
        }
        headers = {"Authorization": f"Bearer {token}"}

        logging.info("Testing Query Endpoint candidates with VALID TOKEN...")

        # Primary candidate based on logs
        is_success = await probe_endpoint(
            session, "POST", "/translate", query_payload, headers
        )

        if is_success:
            logging.info("🚀 SUCCESS! /translate is the correct endpoint.")
        else:
            logging.info("Trying fallbacks...")
            await probe_endpoint(
                session, "POST", "/api/translate", query_payload, headers
            )
            await probe_endpoint(
                session, "POST", "/api/translator/execute", query_payload, headers
            )


if __name__ == "__main__":
    asyncio.run(main())
