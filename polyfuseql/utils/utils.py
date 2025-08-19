import json
import os
import re
from typing import Dict, Any, Type
from datetime import datetime, date
from pydantic import BaseModel, create_model, field_validator
from typing import Union


def _upper_first(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def _camelize(name: str) -> str:
    """Convert snake_case to camelCase (naïve)."""
    result = ""
    upper_next = False
    for ch in name:
        if ch == "_":
            upper_next = True  # skip the underscore, raise flag
            continue
        if upper_next:
            result += ch.upper()
            upper_next = False
        else:
            result += ch
    return result


def camelize_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return {_camelize(k): v for k, v in d.items()}


def env(name: str, default: str | None = None) -> str | None:  # small shorth.
    return os.environ.get(name, default)


def _snake_case(name: str) -> str:
    """Converts camelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _camelize_keys(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Convert snake_case → camelCase for Postgres JSON rows."""

    def camel(s: str) -> str:
        parts = s.split("_")
        return parts[0] + "".join(x.title() for x in parts[1:])

    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError:
            return {}
    return {camel(k): v for k, v in obj.items()}


def get_pydantic_model(tb_name: str, schema: Dict) -> Type[BaseModel]:
    """
    Dynamically creates a Pydantic model from a schema definition
    with a smart field validator to coerce types.
    """

    columns = schema.get("columns", [])

    # Define the fields with a flexible Union type hint
    pydantic_fields = {
        col: (Union[float, int, date, str, None], None) for col in columns
    }

    # Create a base model with the validator
    class TblRowModel(BaseModel):
        @field_validator("*", mode="before")
        @classmethod
        def dynamic_caster(cls, v: Any) -> Any:
            if not isinstance(v, str):
                return v

            v = v.strip()
            if not v:
                return None

            # Try casting to int
            try:
                # Use a more robust check for integers
                if str(int(v)) == v:
                    return int(v)
            except (ValueError, TypeError):
                pass

            # Try casting to float
            try:
                return float(v)
            except (ValueError, TypeError):
                pass

            # Try casting to date
            try:
                return datetime.strptime(v, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

            return v

    # Create the final model inheriting from our base model
    DynamicModel = create_model(
        f"{tb_name.capitalize()}Model", __base__=TblRowModel, **pydantic_fields
    )

    return DynamicModel
