"""
API v1 router — aggregates all endpoint routers.
"""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, tasks, users, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(users.router)
api_router.include_router(ws.router)
