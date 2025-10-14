# src/polyfuseql/app/main.py
"""
Main application file to initialize and run the FastAPI app.
"""
from fastapi import FastAPI

# FIX: Changed imports to be absolute from the 'polyfuseql' package root.
from polyfuseql.app.api import postgres, redis, neo4j, cassandra, mongodb

# Initialize the FastAPI app
app = FastAPI(
    title="PolyFuseQL API",
    description="A robust FastAPI backend for the PolyFuseQL middleware.",
    version="1.0.0",
)

# Include the API routers for each database
app.include_router(postgres.router, prefix="/postgres", tags=["PostgreSQL"])
app.include_router(redis.router, prefix="/redis", tags=["Redis"])
app.include_router(neo4j.router, prefix="/neo4j", tags=["Neo4j"])
app.include_router(cassandra.router, prefix="/cassandra", tags=["Cassandra"])
app.include_router(mongodb.router, prefix="/mongodb", tags=["MongoDB"])


@app.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint for the API.
    """
    return {"message": "Welcome to the PolyFuseQL API!"}
