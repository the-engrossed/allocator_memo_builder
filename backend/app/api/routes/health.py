from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.domain.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.rollback()
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db=db_ok,
        openai_configured=bool(settings.openai_api_key),
        fred_configured=bool(settings.fred_api_key),
    )
