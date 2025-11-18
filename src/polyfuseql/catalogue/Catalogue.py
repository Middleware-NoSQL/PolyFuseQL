import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union

from polyfuseql.config import settings


class Catalogue(dict):
    """
    Manages database schemas, loading them from a JSON file.
    The schema defines tables, their backends, primary keys, and columns.
    """

    def __init__(
        self, schema_path: Union[str, Path, None] = None, **kwargs
    ) -> None:  # noqa:F501
        super().__init__(**kwargs)
        # If a path is explicitly passed, it takes precedence.
        # Otherwise, use the global settings.
        self._schema_path = (
            Path(schema_path)
            if schema_path
            else settings.polyfuseql_schema_path  # noqa:F501
        )

        if not self._schema_path or not self._schema_path.exists():
            msg = "No schema file provided or found. "
            msg += f"Looked for: {self._schema_path}. Catalogue is empty."
            logging.warning(msg)
            return

        self._load_and_validate_schema()

    def _load_and_validate_schema(self) -> None:
        """Loads and validates the schema from the resolved JSON file."""
        logging.info(f"Loading schema from: {self._schema_path}")
        try:
            with open(self._schema_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in schema file {self._schema_path}: {e}"
            ) from e

        if not isinstance(data, dict):
            msg = "Schema file must contain "
            msg += "a JSON object of tables."
            raise TypeError(msg)

        for table_name, schema in data.items():
            self._validate_table_schema(table_name, schema)
            self[table_name.lower()] = schema

        logging.info(f"Successfully loaded and validated {len(data)} tables.")

    def _validate_table_schema(self, table_name: str, schema: Dict) -> None:
        """Validates the structure of a single table's schema."""
        required_keys = {"backend", "pk", "columns"}
        missing_keys = required_keys - schema.keys()
        if missing_keys:
            keys = ", ".join(sorted(missing_keys))
            msg = f"Invalid schema for table '{table_name}': "
            msg += f"Missing required key(s): {keys}. "
            msg += f"Please define them in '{self._schema_path}'."
            raise ValueError(msg)

        if not isinstance(schema["columns"], dict):
            raise TypeError(
                f"The 'columns' for table '{table_name}' must be a dictionary."
            )

    def get_schema(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves the schema for a given table."""
        return self.get(table_name.lower())
