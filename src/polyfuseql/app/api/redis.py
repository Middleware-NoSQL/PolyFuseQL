# src/polyfuseql/app/api/redis.py
"""
API router for Redis operations.
"""
from fastapi import APIRouter, HTTPException

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.schemas.schemas import QueryRequest, QueryResponse
from polyfuseql.app.services import services

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def redis_query(request: QueryRequest):
    """
    Executes a SQL query on the Redis database.
    """
    try:
        results = await services.execute_query(engine="redis", sql=request.sql)
        return {"result": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
