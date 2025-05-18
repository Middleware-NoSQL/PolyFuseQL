import json
import os
import re
from typing import Dict, Any


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


def _env(name: str, default: str | None = None) -> str | None:  # small shorth.
    return os.environ.get(name, default)


def _camelize_keys(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Convert snake_case → camelCase for Postgres JSON rows so that they match
    redis / neo4j payloads."""

    def camel(s: str) -> str:
        return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s)

    if isinstance(obj, str):
        obj = json.loads(obj)
    return {camel(k): v for k, v in obj.items()}
