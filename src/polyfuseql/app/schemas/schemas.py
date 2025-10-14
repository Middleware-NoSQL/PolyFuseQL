# app/schemas/schemas.py
"""
Pydantic schemas for data validation.
"""
from pydantic import BaseModel
from typing import List, Dict, Any


class QueryRequest(BaseModel):
    """
    Schema for a database query request.
    """

    sql: str


class QueryResponse(BaseModel):
    """
    Schema for a database query response.
    """

    result: List[Dict[str, Any]]
