import csv
from typing import Any, Dict, List, Optional

import aiohttp
from pymongo import MongoClient

# FIX: The asynchronous database class is named `AsyncDatabase`.
from pymongo.asynchronous.database import AsyncDatabase as Database
from sqlglot import exp

from polyfuseql.catalogue.Catalogue import Catalogue
from polyfuseql.connector import Connector
from polyfuseql.config import AppSettings
import logging

logger = logging.getLogger(__name__)


class MongoDbConnector(Connector):
    """
    Connector for MongoDB, implementing the full Connector interface.
    Uses an external service for ALL SQL-to-MongoDB query translations.
    """

    def __init__(
        self,
        settings: AppSettings,
        options: Optional[Dict] = None,
        catalogue: Optional[Catalogue] = None,
    ):
        super().__init__(options, catalogue)
        self.settings = settings.mongodb
        self.translator_url = settings.mongo_translator_url
        self._client: MongoClient | None = None
        self._db: Database | None = None
        self._http_session = aiohttp.ClientSession()
        logger.info(
            f"MongoDbConnector initialized for database: {self.settings.db}"
        )  # noqa:E501

    async def connect(self):
        """Establishes a connection to the MongoDB server."""
        if self._client:
            return
        try:
            connection_string = (
                f"mongodb://{self.settings.user}:{self.settings.password}@"
                f"{self.settings.host}:{self.settings.port}/"
            )
            self._client = MongoClient(connection_string, asyncio=True)
            self._db = self._client[self.settings.db]
            await self.ping()
            logger.info("Successfully connected to MongoDB.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self._client = None
            self._db = None
            raise

    async def disconnect(self):
        """Closes the connection to the MongoDB server."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB connection closed.")
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def ping(self) -> bool:
        """Pings the MongoDB server to check the connection."""
        if not self._client:
            raise ConnectionError("Not connected to MongoDB.")
        try:
            await self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.error(f"MongoDB ping failed: {e}")
            return False

    def _format_value(self, value: Any) -> str:
        """Formats a Python value into a SQL literal for the translator."""
        if isinstance(value, str):
            # Use triple quotes to handle nested quotes robustly.
            return f"""'{value.replace("'", "''")}'"""
        if value is None:
            return "NULL"
        return str(value)

    async def _translate_sql_to_mongo(self, sql_query: str) -> Dict[str, Any]:
        """Sends SQL to the translation service and returns
        the MongoDB query parts."""
        url = f"{self.translator_url}/api/translate"
        payload = {"sql_query": sql_query}
        try:
            async with self._http_session.post(url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Error calling translation service: {e}")
            raise ConnectionError(
                f"Failed to communicate with translator: {e}"
            )  # noqa:E501

    async def query(
        self, sql: str, params: tuple = None
    ) -> List[Dict[str, Any]]:  # noqa:E501
        """Translates a SQL query to a MongoDB find command and executes it."""
        await self.connect()
        mongo_parts = await self._translate_sql_to_mongo(sql)

        collection_name = mongo_parts.get("collection")
        query = mongo_parts.get("query", {})
        projection = mongo_parts.get("projection")

        if not collection_name:
            raise ValueError("Translation did not return a collection name.")

        collection = self._db[collection_name]
        cursor = collection.find(query, projection)
        return await cursor.to_list(length=None)

    async def count(self, entity: str) -> int:
        """Counts documents by generating a 'SELECT COUNT' query."""
        sql = f"SELECT COUNT(*) FROM {entity}"
        # The translator for COUNT should return a single doc like {'count': N}
        result = await self.query(sql)
        if result and result[0]:
            # Return the first value in the result document
            return next(iter(result[0].values()), 0)
        return 0

    async def get(
        self, entity: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any] | None:  # noqa:E501
        """Fetches a document by its primary key."""
        pk_val_formatted = self._format_value(pk_val)
        sql = f"SELECT * FROM {entity} WHERE {pk_col} = {pk_val_formatted}"
        result = await self.query(sql)
        return result[0] if result else None

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        """Fetches all documents in a collection."""
        sql = f"SELECT * FROM {entity}"
        return await self.query(sql)

    async def insert(self, entity: str, payload: Dict[str, Any]) -> Any:
        """Inserts a document by generating an 'INSERT' query."""
        cols = ", ".join(payload.keys())
        vals = ", ".join(self._format_value(v) for v in payload.values())
        sql = f"INSERT INTO {entity} ({cols}) VALUES ({vals})"

        await self.connect()
        # For insert, we don't expect a query back, just confirmation.
        await self._translate_sql_to_mongo(sql)
        # The translator API for INSERT doesn't return the inserted ID.
        # Returning True indicates the operation was sent successfully.
        return True

    async def update(
        self, entity: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        """Updates a document by generating an 'UPDATE' query."""
        set_clause = ", ".join(
            f"{k} = {self._format_value(v)}" for k, v in payload.items()
        )
        pk_val_formatted = self._format_value(pk_val)
        sql = f"UPDATE {entity} SET {set_clause} WHERE {pk_col} = {pk_val_formatted}"  # noqa:E501

        await self.connect()
        await self._translate_sql_to_mongo(sql)
        # NOTE: The translator API does not return the modified count.
        # Assuming success, we return 1 as per the abstract method's
        # expectation.
        return 1

    async def delete(self, entity: str, pk_col: str, pk_val: Any) -> int:
        """Deletes a document by generating a 'DELETE' query."""
        pk_val_formatted = self._format_value(pk_val)
        sql = f"DELETE FROM {entity} WHERE {pk_col} = {pk_val_formatted}"

        await self.connect()
        await self._translate_sql_to_mongo(sql)
        # NOTE: The translator API does not return the deleted count.
        # Assuming success, we return 1.
        return 1

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a JOIN query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes a GROUP BY query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Executes an aggregation query by translating its AST to SQL."""
        sql = ast.sql()
        return await self.query(sql)

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        Bulk inserts data from a CSV file directly using the driver.
        NOTE: This method bypasses the translator for performance reasons.
        """
        await self.connect()
        try:
            with open(file_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                documents = list(reader)
                if not documents:
                    return 0

                collection = self._db[table_name]
                result = await collection.insert_many(documents)
                return len(result.inserted_ids)
        except FileNotFoundError:
            logger.error(f"Bulk insert file not found: {file_path}")
            return 0
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}")
            raise
