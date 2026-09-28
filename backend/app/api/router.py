from fastapi import APIRouter

from app.api.routes.analyses import router as analyses_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(analyses_router)
