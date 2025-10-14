# src/polyfuseql/app/api/neo4j.py
"""
API router for Neo4j operations.
"""
from fastapi import APIRouter, HTTPException

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.schemas.schemas import QueryRequest, QueryResponse
from polyfuseql.app.services import services

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def neo4j_query(request: QueryRequest):
    """
    Executes a SQL query on the Neo4j database.
    """
    try:
        results = await services.execute_query(engine="neo4j", sql=request.sql)
        return {"result": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
