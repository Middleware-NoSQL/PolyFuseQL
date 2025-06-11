import json
import pathlib
from typing import Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repo root guess
DEFAULT_MAPPING: dict[str, Tuple[str, str]] = {
    # table : (backend, pkCol)
    # Corrected PK names to match the actual data properties
    "customers": ("postgres", "customer_id"),
    "products": ("postgres", "productID"),
    "customer": (
        "neo4j",
        "customerID",
    ),  # Neo4j uses customerID (camelCase with capital ID)
    "product": ("neo4j", "productID"),  # Neo4j uses productID
    "person": ("neo4j", "id"),  # Added for the insert test
}


class Catalogue(dict):
    """table → (backend, pkCol). Loads mapping.json if present."""

    def __init__(self) -> None:  # type: ignore[override]
        super().__init__(DEFAULT_MAPPING)
        mapping_file = ROOT / "catalogue" / "mapping.json"
        if mapping_file.exists():
            with mapping_file.open() as fh:
                data = json.load(fh)
            # normalize keys → lower
            for tbl, cfg in data.items():
                self[tbl.lower()] = (
                    cfg["backend"],
                    cfg["pk"],
                )
