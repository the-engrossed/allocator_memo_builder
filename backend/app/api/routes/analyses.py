from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.domain.models import Analysis
from app.domain.schemas import AnalysisResponse
from app.services.ingestion import analysis_to_response, create_analysis

router = APIRouter(tags=["analyses"])


@router.post("/analyses", response_model=AnalysisResponse, status_code=201)
async def upload_analysis(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="CSV exceeds the 5 MB upload limit")
    try:
        analysis = create_analysis(db, filename=filename, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return analysis_to_response(analysis)


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: UUID, db: Session = Depends(get_db)) -> AnalysisResponse:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis_to_response(analysis)
