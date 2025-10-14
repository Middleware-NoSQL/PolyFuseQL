# src/polyfuseql/app/api/mongodb.py
"""
API router for MongoDB operations.
"""
from fastapi import APIRouter, HTTPException

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.schemas.schemas import QueryRequest, QueryResponse
from polyfuseql.app.services import services

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def mongodb_query(request: QueryRequest):
    """
    Executes a SQL query on the MongoDB database.
    """
    try:
        results = await services.execute_query(
            engine="mongodb", sql=request.sql
        )  # noqa:E501
        return {"result": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
