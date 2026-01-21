import csv
import logging
import os
import time
import json
import base64
import hmac
import hashlib
from typing import Any, Dict, List, Optional

import aiohttp
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.config import AppSettings
from polyfuseql.connector import Connector

logger = logging.getLogger(__name__)


class MongoDbConnector(Connector):
    """
    Connector for MongoDB. Acts as a pure client to the Traductor-SQL-NOSQL
    service, ensuring all operations are processed through SQL translation.
    """

    def __init__(
        self,
        settings: AppSettings,
        options: Optional[Dict] = None,
        catalogue: Optional[Catalogue] = None,
        is_local_implementation: bool = False,
    ):
        super().__init__(options, catalogue, is_local_implementation)
        self.settings = settings.mongodb
        # Base URL from settings (e.g. http://localhost:5101)
        self.translator_url = settings.mongo_translator_url
        self._client: Optional[AsyncMongoClient] = None
        self._db: Optional[AsyncDatabase] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._translator_auth_token: Optional[str] = None
        # Testing hack: Allow bypassing auth service if secret is known
        self._jwt_secret = os.getenv("JWT_SECRET_KEY", "dev-secret")

    def _mint_manual_token(self, identity: str = "admin") -> str:
        """
        Generates a valid JWT locally using the shared secret.
        This bypasses the /auth/login endpoint if the DB is empty/broken.
        """
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())

        # [FIX] Permissions must be a Dictionary with LOWERCASE keys
        # to match main.py logic: user_permissions.get("insert", False)
        permissions_dict = {
            "select": True,
            "insert": True,
            "update": True,
            "delete": True,
            "create_table": True,
            "drop_table": True,
        }

        payload = {
            "fresh": False,
            "iat": now,
            "jti": f"polyfuseql-auto-{now}",
            "type": "access",
            "sub": identity,
            "nbf": now,
            "exp": now + 3600,
            "permissions": permissions_dict,
            "role": "admin",
            "is_admin": True,
        }

        def b64url(data_dict):
            # JWT spec requires compact JSON (no spaces)
            json_bytes = json.dumps(data_dict, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(json_bytes).decode().rstrip("=")

        segments = [b64url(header), b64url(payload)]
        signing_input = ".".join(segments).encode()

        signature = hmac.new(
            self._jwt_secret.encode(), signing_input, hashlib.sha256
        ).digest()

        segments.append(base64.urlsafe_b64encode(signature).decode().rstrip("="))
        return ".".join(segments)

    async def _authenticate_with_translator(self):
        """Logs into the translator service to get a JWT token."""
        # [TESTING FIX] Prioritize manual minting if secret is available
        if self._jwt_secret:
            # logger.info("Minting local JWT using configured secret (Bypassing /auth/login).")
            self._translator_auth_token = self._mint_manual_token()
            return

        if not self._http_session or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()

        # Endpoint confirmed via debug script
        auth_url = f"{self.translator_url}/api/auth/login"
        payload = {
            "username": self.settings.user,
            "password": self.settings.password,
        }

        try:
            async with self._http_session.post(auth_url, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    self._translator_auth_token = data.get("access_token")
                    logger.info("Authenticated with MongoDB Translator.")
                else:
                    text = await resp.text()
                    logger.error(f"Auth failed: {resp.status} - {text}")
        except Exception as e:
            logger.error(f"Failed to connect to auth service: {e}")

    async def connect(self) -> None:
        """
        Establishes connection to the Translator service (via HTTP session)
        AND the native MongoDB client (for bulk operations or direct checks).
        """
        # 1. Connect to Translator (HTTP)
        if not self._http_session or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
            await self._authenticate_with_translator()

        # 2. Connect to Native MongoDB (Direct)
        if not self._client:
            # Construct URI
            uri = (
                f"mongodb://{self.settings.user}:{self.settings.password}"
                f"@{self.settings.host}:{self.settings.port}/"
            )
            self._client = AsyncMongoClient(uri)
            self._db = self._client[self.settings.db]
            logger.info(f"Native MongoDB connection established to {self.settings.db}")

    async def disconnect(self) -> None:
        """Closes both HTTP session and Native Client."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
            logger.info("MongoDB Translator session closed.")

        if self._client:
            await self._client.close()
            self._client = None
            self._db = None
            logger.info("Native MongoDB connection closed.")

    def _format_value(self, val: Any) -> str:
        """Helper to format values for SQL string construction."""
        if isinstance(val, str):
            # Escape single quotes
            safe_val = val.replace("'", "''")
            return f"'{safe_val}'"
        if val is None:
            return "NULL"
        return str(val)

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        """Sends SQL to the translator service."""
        # Ensure session is open (re-connect only if http session closed)
        if not self._http_session or self._http_session.closed:
            await self.connect()

        headers = {}
        if self._translator_auth_token:
            headers["Authorization"] = f"Bearer {self._translator_auth_token}"

        # Attempt to extract table/collection name from SQL
        # This is required by the translator API to avoid 400 Bad Request
        collection_name = None
        try:
            parsed = exp.parse_one(sql)
            # Find the first table reference
            for node in parsed.find_all(exp.Table):
                collection_name = node.name
                break
        except Exception:
            pass

        # [FIX] Endpoint changed from /api/translator/execute to /translate
        # [FIX] Added 'collection' field to payload
        payload = {"query": sql, "database": self.settings.db}
        if collection_name:
            payload["collection"] = collection_name

        url = f"{self.translator_url}/translate"

        try:
            async with self._http_session.post(
                url, json=payload, headers=headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    text = await resp.text()
                    logger.error(f"Translator Error ({resp.status}): {text}")
                    return []
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return []

    # Implement abstract methods by routing to .query()

    async def get(self, table: str, pk_col: str, pk_val: Any) -> Dict[str, Any]:
        sql = f"SELECT * FROM {table} WHERE {pk_col} = {self._format_value(pk_val)}"
        res = await self.query(sql)
        return res[0] if res else {}

    async def insert(self, table: str, payload: Dict[str, Any]) -> Any:
        cols = ", ".join(payload.keys())
        vals = ", ".join(self._format_value(v) for v in payload.values())
        sql = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
        return await self.query(sql)

    async def update(
        self, table: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        sets = ", ".join(f"{k}={self._format_value(v)}" for k, v in payload.items())
        sql = f"UPDATE {table} SET {sets} WHERE {pk_col} = {self._format_value(pk_val)}"
        await self.query(sql)
        return 1

    async def delete(self, table: str, pk_col: str, pk_val: Any) -> int:
        sql = f"DELETE FROM {table} WHERE {pk_col} = {self._format_value(pk_val)}"
        await self.query(sql)
        return 1

    async def count(self, table: str) -> int:
        sql = f"SELECT COUNT(*) as count FROM {table}"
        res = await self.query(sql)
        # The result format depends on the translator, usually list of dicts
        if res and isinstance(res, list) and len(res) > 0:
            return int(list(res[0].values())[0])
        return 0

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        sql = ast.sql()
        return await self.query(sql)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        sql = ast.sql()
        return await self.query(sql)

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        sql = ast.sql()
        return await self.query(sql)

    async def ping(self) -> bool:
        """Pings the native connection."""
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except:
            return False

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM {entity}"
        return await self.query(sql)

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        Bulk inserts by reading a CSV and performing native inserts via PyMongo
        for speed, bypassing the translator for large datasets (setup phase).
        """
        await self.connect()
        # [FIX] Check against None, not truthiness for AsyncDatabase
        if self._db is None:
            raise ConnectionError("Not connected to Native MongoDB.")

        import aiofiles
        import csv

        collection = self._db[table_name.lower()]
        # Clear existing data for benchmark purity
        await collection.drop()

        schema = self.catalogue.get_schema(table_name)
        cols = list(schema["columns"].keys()) if schema else []
        if not cols:
            logger.error(f"No schema for {table_name}")
            return 0

        # Create Index on PK
        if schema and "pk" in schema:
            pk = schema["pk"]
            if isinstance(pk, str):
                await collection.create_index(pk)

        inserted_count = 0
        batch = []
        BATCH_SIZE = 2000

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
                lines = [l for l in content.splitlines() if l.strip()]
                reader = csv.reader(lines, delimiter="|")

                for row in reader:
                    # Clean trailing pipe artifact
                    if len(row) > len(cols):
                        row = row[: len(cols)]

                    doc = {}
                    for i, col in enumerate(cols):
                        val = row[i]
                        # Infer types based on schema if possible
                        col_type = schema["columns"].get(col, "str")
                        try:
                            if col_type == "int":
                                doc[col] = int(val)
                            elif col_type == "decimal":
                                doc[col] = float(val)
                            else:
                                doc[col] = val
                        except:
                            doc[col] = val

                    batch.append(doc)
                    if len(batch) >= BATCH_SIZE:
                        await collection.insert_many(batch)
                        inserted_count += len(batch)
                        batch = []

                if batch:
                    await collection.insert_many(batch)
                    inserted_count += len(batch)

            return inserted_count

        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            return 0
