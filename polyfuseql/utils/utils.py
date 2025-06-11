import json
import os
import re
from typing import Dict, Any


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
        # This implementation is better than the previous one
        parts = s.split("_")
        return parts[0] + "".join(x.title() for x in parts[1:])

    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError:
            return {}
    return {camel(k): v for k, v in obj.items()}
