"""
API v1 router — aggregates all endpoint routers.
Note: extract and agent routers are mounted directly on the app
in main.py because they use different URL prefixes (/api/v4 and /api/v1/agent).
"""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, tasks, users, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(users.router)
api_router.include_router(ws.router)
