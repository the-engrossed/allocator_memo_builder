import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import Mandate
from app.domain.schemas import MandateIn

VALID_MANDATE: dict = {
    "target_return_bps": 1000,
    "max_mgmt_fee_bps": 200,
    "max_perf_fee_bps": 2000,
    "max_notice_days": 90,
    "max_lockup_months": 12,
    "min_liquidity_frequency": "quarterly",
    "max_volatility_bps": 1500,
    "max_drawdown_bps": 2000,
    "min_track_record_months": 36,
    "preferred_strategies": ["Macro", "Equity L/S", "Credit"],
    "excluded_strategies": ["Crypto"],
    "strategy_concentration_cap_bps": 4000,
    "max_candidates": 5,
}

UPPER_BOUNDS = {
    "target_return_bps": 10_000,
    "max_mgmt_fee_bps": 10_000,
    "max_perf_fee_bps": 10_000,
    "strategy_concentration_cap_bps": 10_000,
    "max_volatility_bps": 10_000,
    "max_drawdown_bps": 10_000,
    "max_notice_days": 3650,
    "max_lockup_months": 120,
    "min_track_record_months": 360,
    "max_candidates": 20,
}


def _mandate(**overrides: object) -> dict:
    return {**VALID_MANDATE, **overrides}


def _url(analysis_id: uuid.UUID) -> str:
    return f"/api/analyses/{analysis_id}/mandate"


# --- Schema validation (no database) ---------------------------------------------------


def test_valid_payload_is_accepted() -> None:
    assert MandateIn.model_validate(VALID_MANDATE).model_dump(mode="json") == VALID_MANDATE


@pytest.mark.parametrize("field", sorted(UPPER_BOUNDS))
def test_bounds_are_inclusive(field: str) -> None:
    MandateIn.model_validate(_mandate(**{field: UPPER_BOUNDS[field]}))
    lower = 1 if field == "max_candidates" else 0
    MandateIn.model_validate(_mandate(**{field: lower}))


@pytest.mark.parametrize("field", sorted(UPPER_BOUNDS))
def test_values_outside_bounds_are_rejected(field: str) -> None:
    lower = 1 if field == "max_candidates" else 0
    for value in (lower - 1, UPPER_BOUNDS[field] + 1):
        with pytest.raises(ValidationError):
            MandateIn.model_validate(_mandate(**{field: value}))


@pytest.mark.parametrize("value", [1000.0, 1000.5, "1000", True, None])
def test_integer_fields_are_strict(value: object) -> None:
    with pytest.raises(ValidationError):
        MandateIn.model_validate(_mandate(target_return_bps=value))


@pytest.mark.parametrize("field", sorted(VALID_MANDATE))
def test_every_field_is_required(field: str) -> None:
    payload = _mandate()
    del payload[field]
    with pytest.raises(ValidationError):
        MandateIn.model_validate(payload)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MandateIn.model_validate(_mandate(target_return=1000))


@pytest.mark.parametrize("field", ["preferred_strategies", "excluded_strategies"])
def test_strategies_are_trimmed_and_deduplicated_in_order(field: str) -> None:
    other = "excluded_strategies" if field == "preferred_strategies" else "preferred_strategies"
    mandate = MandateIn.model_validate(
        _mandate(**{field: ["  Credit ", "Macro", "Credit", "Macro  "], other: []})
    )
    assert getattr(mandate, field) == ["Credit", "Macro"]


@pytest.mark.parametrize("field", ["preferred_strategies", "excluded_strategies"])
def test_strategy_lists_may_be_empty(field: str) -> None:
    assert getattr(MandateIn.model_validate(_mandate(**{field: []})), field) == []


@pytest.mark.parametrize("field", ["preferred_strategies", "excluded_strategies"])
@pytest.mark.parametrize("strategies", [[""], ["   "], ["Macro", " "], [1], "Macro", None])
def test_invalid_strategy_lists_are_rejected(field: str, strategies: object) -> None:
    with pytest.raises(ValidationError):
        MandateIn.model_validate(_mandate(**{field: strategies}))


def test_strategy_cannot_be_preferred_and_excluded() -> None:
    with pytest.raises(ValidationError, match="both preferred and excluded: Credit"):
        MandateIn.model_validate(
            _mandate(preferred_strategies=["Macro", " Credit"], excluded_strategies=["Credit "])
        )


@pytest.mark.parametrize("value", ["monthly", "quarterly", "semiannual", "annual"])
def test_liquidity_frequencies_are_accepted(value: str) -> None:
    mandate = MandateIn.model_validate(_mandate(min_liquidity_frequency=value))
    assert mandate.min_liquidity_frequency == value


@pytest.mark.parametrize("value", ["Quarterly", "semi-annual", "weekly", "", 3, None])
def test_unknown_liquidity_frequency_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        MandateIn.model_validate(_mandate(min_liquidity_frequency=value))


# --- API against Postgres ---------------------------------------------------------------


def test_put_creates_mandate(client: TestClient, analysis_id: uuid.UUID) -> None:
    response = client.put(_url(analysis_id), json=VALID_MANDATE)

    assert response.status_code == 201
    body = response.json()
    assert body["analysis_id"] == str(analysis_id)
    assert {key: body[key] for key in VALID_MANDATE} == VALID_MANDATE
    assert body["created_at"] == body["updated_at"]

    fetched = client.get(_url(analysis_id))
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_put_replaces_existing_mandate(client: TestClient, analysis_id: uuid.UUID) -> None:
    created = client.put(_url(analysis_id), json=VALID_MANDATE).json()
    replacement = _mandate(
        target_return_bps=800,
        preferred_strategies=["Credit"],
        max_candidates=3,
    )

    response = client.put(_url(analysis_id), json=replacement)

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in replacement} == replacement
    assert body["created_at"] == created["created_at"]
    assert datetime.fromisoformat(body["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )
    assert client.get(_url(analysis_id)).json() == body


def test_identical_put_is_idempotent(
    client: TestClient, analysis_id: uuid.UUID, db_session: Session
) -> None:
    first = client.put(_url(analysis_id), json=VALID_MANDATE)
    second = client.put(_url(analysis_id), json=VALID_MANDATE)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    count = db_session.scalar(
        select(func.count()).select_from(Mandate).where(Mandate.analysis_id == analysis_id)
    )
    assert count == 1


def test_put_normalizes_strategies(client: TestClient, analysis_id: uuid.UUID) -> None:
    response = client.put(
        _url(analysis_id),
        json=_mandate(
            preferred_strategies=[" Macro", "Macro", "Credit "],
            excluded_strategies=["Crypto ", "Crypto"],
        ),
    )

    assert response.status_code == 201
    assert response.json()["preferred_strategies"] == ["Macro", "Credit"]
    assert response.json()["excluded_strategies"] == ["Crypto"]


def test_put_accepts_empty_preferences(client: TestClient, analysis_id: uuid.UUID) -> None:
    payload = _mandate(preferred_strategies=[], excluded_strategies=[])

    response = client.put(_url(analysis_id), json=payload)

    assert response.status_code == 201
    assert response.json()["preferred_strategies"] == []
    assert client.get(_url(analysis_id)).json()["excluded_strategies"] == []


@pytest.mark.parametrize(
    "payload",
    [
        _mandate(max_candidates=0),
        _mandate(max_candidates=21),
        _mandate(max_notice_days=-1),
        _mandate(max_mgmt_fee_bps=10_001),
        _mandate(target_return_bps=10.5),
        _mandate(preferred_strategies=["  "]),
        _mandate(min_liquidity_frequency="weekly"),
        _mandate(max_drawdown_bps=10_001),
        _mandate(excluded_strategies=["Macro"]),
        _mandate(unexpected=1),
        {"target_return_bps": 1000},
    ],
)
def test_invalid_put_is_rejected_and_not_persisted(
    client: TestClient, analysis_id: uuid.UUID, payload: dict
) -> None:
    response = client.put(_url(analysis_id), json=payload)

    assert response.status_code == 422
    assert client.get(_url(analysis_id)).status_code == 404


def test_invalid_update_leaves_existing_mandate_unchanged(
    client: TestClient, analysis_id: uuid.UUID
) -> None:
    saved = client.put(_url(analysis_id), json=VALID_MANDATE).json()

    response = client.put(_url(analysis_id), json=_mandate(max_candidates=50))

    assert response.status_code == 422
    assert client.get(_url(analysis_id)).json() == saved


def test_put_unknown_analysis_returns_404(client: TestClient) -> None:
    missing = uuid.uuid4()

    response = client.put(_url(missing), json=VALID_MANDATE)

    assert response.status_code == 404
    assert response.json() == {"detail": f"Analysis {missing} not found."}


def test_get_unknown_analysis_returns_404(client: TestClient) -> None:
    missing = uuid.uuid4()

    response = client.get(_url(missing))

    assert response.status_code == 404
    assert response.json() == {"detail": f"Analysis {missing} not found."}


def test_get_unconfigured_mandate_returns_404(
    client: TestClient, analysis_id: uuid.UUID
) -> None:
    response = client.get(_url(analysis_id))

    assert response.status_code == 404
    assert response.json() == {"detail": f"Mandate not configured for analysis {analysis_id}."}


def test_malformed_analysis_id_returns_422(client: TestClient) -> None:
    assert client.put("/api/analyses/not-a-uuid/mandate", json=VALID_MANDATE).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_candidates": 0},
        {"min_liquidity_frequency": "weekly"},
        {"max_volatility_bps": -1},
        {"max_drawdown_bps": 10_001},
        {"min_track_record_months": 361},
    ],
)
def test_database_enforces_bounds(
    db_session: Session, analysis_id: uuid.UUID, overrides: dict
) -> None:
    now = datetime.now(timezone.utc)
    nested = db_session.begin_nested()
    db_session.add(
        Mandate(
            analysis_id=analysis_id,
            created_at=now,
            updated_at=now,
            **_mandate(**overrides),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    nested.rollback()


def test_database_allows_empty_preferred_strategies(
    db_session: Session, analysis_id: uuid.UUID
) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(
        Mandate(
            analysis_id=analysis_id,
            created_at=now,
            updated_at=now,
            **_mandate(preferred_strategies=[], excluded_strategies=[]),
        )
    )
    db_session.flush()
