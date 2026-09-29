from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.schemas import EvidenceRegistryResponse
from app.services.memos import evidence_for_run
from app.services.ranking_runs import RankingRunNotFoundError

router = APIRouter(tags=["evidence"])


@router.get("/ranking-runs/{run_id}/evidence", response_model=EvidenceRegistryResponse)
def read_run_evidence(run_id: UUID, db: Session = Depends(get_db)) -> EvidenceRegistryResponse:
    """Rebuilt from the immutable run on each request; memos carry their own snapshot."""
    try:
        return evidence_for_run(db, run_id)
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
