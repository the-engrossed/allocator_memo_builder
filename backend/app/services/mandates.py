"""Mandate configuration: one persisted mandate per analysis, replaced wholesale on update."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.models import Analysis, Mandate
from app.domain.schemas import MandateIn


class AnalysisNotFoundError(LookupError):
    pass


class MandateNotFoundError(LookupError):
    pass


def get_mandate(session: Session, analysis_id: uuid.UUID) -> Mandate:
    _require_analysis(session, analysis_id)
    mandate = session.get(Mandate, analysis_id)
    if mandate is None:
        raise MandateNotFoundError(f"Mandate not configured for analysis {analysis_id}.")
    return mandate


def upsert_mandate(
    session: Session, analysis_id: uuid.UUID, payload: MandateIn
) -> tuple[Mandate, bool]:
    """Create or fully replace the analysis mandate. Returns (mandate, created).

    Replaying an identical payload is a no-op and leaves updated_at unchanged.
    """
    _require_analysis(session, analysis_id)
    values = payload.model_dump(mode="json")
    now = datetime.now(timezone.utc)

    mandate = session.get(Mandate, analysis_id)
    if mandate is None:
        mandate = Mandate(analysis_id=analysis_id, created_at=now, updated_at=now, **values)
        session.add(mandate)
        session.flush()
        return mandate, True

    if any(getattr(mandate, name) != value for name, value in values.items()):
        for name, value in values.items():
            setattr(mandate, name, value)
        mandate.updated_at = now
        session.flush()
    return mandate, False


def _require_analysis(session: Session, analysis_id: uuid.UUID) -> None:
    if session.get(Analysis, analysis_id) is None:
        raise AnalysisNotFoundError(f"Analysis {analysis_id} not found.")
