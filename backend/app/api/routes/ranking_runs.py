from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.schemas import RankingRunResponse
from app.services.mandates import AnalysisNotFoundError
from app.services.ranking_runs import (
    RankingRunConflictError,
    RankingRunNotFoundError,
    create_ranking_run,
    get_latest_ranking_run,
    get_ranking_run,
    run_to_response,
)

router = APIRouter(tags=["ranking-runs"])


@router.post(
    "/analyses/{analysis_id}/ranking-runs", response_model=RankingRunResponse, status_code=201
)
def post_ranking_run(analysis_id: UUID, db: Session = Depends(get_db)) -> RankingRunResponse:
    try:
        run = create_ranking_run(db, analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RankingRunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_to_response(run)


@router.get("/analyses/{analysis_id}/ranking-runs/latest", response_model=RankingRunResponse)
def read_latest_ranking_run(
    analysis_id: UUID, db: Session = Depends(get_db)
) -> RankingRunResponse:
    try:
        run = get_latest_ranking_run(db, analysis_id)
    except (AnalysisNotFoundError, RankingRunNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run_to_response(run)


@router.get("/ranking-runs/{run_id}", response_model=RankingRunResponse)
def read_ranking_run(run_id: UUID, db: Session = Depends(get_db)) -> RankingRunResponse:
    try:
        run = get_ranking_run(db, run_id)
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run_to_response(run)
