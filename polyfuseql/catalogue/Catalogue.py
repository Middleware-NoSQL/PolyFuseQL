import json
import logging
import os
import pathlib
from pathlib import Path
from typing import Dict, Any, Optional, Union

# Define ROOT more robustly
ROOT = pathlib.Path(__file__).resolve().parent.parent


class Catalogue(dict):
    """
    Manages database schemas, loading them from a JSON file.
    The schema defines tables, their backends, primary keys, and columns.
    """

    def __init__(
        self, schema_path: Union[str, Path, None] = None, **kwargs
    ) -> None:  # noqa:F501
        super().__init__(**kwargs)
        self._schema_path = self._resolve_schema_path(schema_path)

        if not self._schema_path or not self._schema_path.exists():
            msg = "No schema file provided or found. "
            msg += "Catalogue is empty."
            logging.warning(msg)
            return

        self._load_and_validate_schema()

    def _resolve_schema_path(
        self, schema_path: Union[str, Path, None]
    ) -> Optional[Path]:
        """
        Determines the schema file path to use.
        Precedence: explicit path > env var > default path.
        """
        if schema_path:
            path = Path(schema_path)
            if not path.exists():
                raise FileNotFoundError(f"Schema file not found at: {path}")
            return path

        if env_path := os.getenv("POLYFUSEQL_SCHEMA_PATH"):
            path = Path(env_path)
            if not path.exists():
                msg = "Schema file from POLYFUSEQL_SCHEMA_PATH not found at: "
                msg += f"{path}"
                raise FileNotFoundError(msg)
            return path

        default_path = ROOT / "catalogue" / "schemas.json"
        if default_path.exists():
            return default_path

        return None

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
            keys = ", ".join(sorted(list(missing_keys)))
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
