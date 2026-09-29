from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.schemas import MemoResponse
from app.services.memos import (
    MemoNotFoundError,
    create_memo,
    get_latest_memo,
    get_memo,
    memo_to_response,
)
from app.services.ranking_runs import RankingRunNotFoundError

router = APIRouter(tags=["memos"])


@router.post("/ranking-runs/{run_id}/memos", response_model=MemoResponse, status_code=201)
def post_memo(run_id: UUID, db: Session = Depends(get_db)) -> MemoResponse:
    try:
        memo = create_memo(db, run_id)
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return memo_to_response(memo)


@router.get("/ranking-runs/{run_id}/memos/latest", response_model=MemoResponse)
def read_latest_memo(run_id: UUID, db: Session = Depends(get_db)) -> MemoResponse:
    try:
        memo = get_latest_memo(db, run_id)
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if memo is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NO_MEMO", "message": f"Ranking run {run_id} has no memo yet."},
        )
    return memo_to_response(memo)


@router.get("/memos/{memo_id}", response_model=MemoResponse)
def read_memo(memo_id: UUID, db: Session = Depends(get_db)) -> MemoResponse:
    try:
        memo = get_memo(db, memo_id)
    except MemoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return memo_to_response(memo)
