from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.schemas import MandateIn, MandateResponse
from app.services.mandates import (
    AnalysisNotFoundError,
    MandateNotFoundError,
    get_mandate,
    upsert_mandate,
)

router = APIRouter(tags=["mandates"])


@router.put(
    "/analyses/{analysis_id}/mandate",
    response_model=MandateResponse,
    responses={201: {"model": MandateResponse, "description": "Mandate created"}},
)
def put_mandate(
    analysis_id: UUID,
    payload: MandateIn,
    response: Response,
    db: Session = Depends(get_db),
) -> MandateResponse:
    try:
        mandate, created = upsert_mandate(db, analysis_id, payload)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return MandateResponse.model_validate(mandate)


@router.get("/analyses/{analysis_id}/mandate", response_model=MandateResponse)
def read_mandate(analysis_id: UUID, db: Session = Depends(get_db)) -> MandateResponse:
    try:
        mandate = get_mandate(db, analysis_id)
    except (AnalysisNotFoundError, MandateNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MandateResponse.model_validate(mandate)
