from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class DecisionWindowIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    context: str = Field(default="", max_length=5000)
    opens_at: str | None = Field(default=None, max_length=80)
    closes_at: str | None = Field(default=None, max_length=80)
    urgency: str = Field(default="medium", max_length=80)
    authority_required: str = Field(default="manager", max_length=120)
    status: str = Field(default="open", max_length=80)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    decision_window_id: str | None = Field(default=None, max_length=200)


class DecisionWindowOut(BaseModel):
    decision_window_id: str
    principal_id: str
    title: str
    context: str
    opens_at: str | None
    closes_at: str | None
    urgency: str
    authority_required: str
    status: str
    notes: str
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class DeadlineWindowIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    start_at: str | None = Field(default=None, max_length=80)
    end_at: str | None = Field(default=None, max_length=80)
    status: str = Field(default="open", max_length=80)
    priority: str = Field(default="medium", max_length=80)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    window_id: str | None = Field(default=None, max_length=200)


class DeadlineWindowOut(BaseModel):
    window_id: str
    principal_id: str
    title: str
    start_at: str | None
    end_at: str | None
    status: str
    priority: str
    notes: str
    source_json: dict[str, object]
    created_at: str
    updated_at: str


def _decision_window_out(row) -> DecisionWindowOut:  # type: ignore[no-untyped-def]
    return DecisionWindowOut(
        decision_window_id=row.decision_window_id,
        principal_id=row.principal_id,
        title=row.title,
        context=row.context,
        opens_at=row.opens_at,
        closes_at=row.closes_at,
        urgency=row.urgency,
        authority_required=row.authority_required,
        status=row.status,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _deadline_window_out(row) -> DeadlineWindowOut:  # type: ignore[no-untyped-def]
    return DeadlineWindowOut(
        window_id=row.window_id,
        principal_id=row.principal_id,
        title=row.title,
        start_at=row.start_at,
        end_at=row.end_at,
        status=row.status,
        priority=row.priority,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/decision-windows")
def upsert_memory_decision_window(
    body: DecisionWindowIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionWindowOut:
    row = container.memory_runtime.upsert_decision_window(
        principal_id=resolve_principal_id(body.principal_id, context),
        title=body.title,
        context=body.context,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        urgency=body.urgency,
        authority_required=body.authority_required,
        status=body.status,
        notes=body.notes,
        source_json=body.source_json,
        decision_window_id=body.decision_window_id,
    )
    return _decision_window_out(row)


@router.get("/decision-windows")
def list_memory_decision_windows(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[DecisionWindowOut]:
    rows = container.memory_runtime.list_decision_windows(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_decision_window_out(row) for row in rows]


@router.get("/decision-windows/{decision_window_id}")
def get_memory_decision_window(
    decision_window_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionWindowOut:
    row = container.memory_runtime.get_decision_window(
        decision_window_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="decision_window_not_found")
    return _decision_window_out(row)


@router.post("/deadline-windows")
def upsert_memory_deadline_window(
    body: DeadlineWindowIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeadlineWindowOut:
    row = container.memory_runtime.upsert_deadline_window(
        principal_id=resolve_principal_id(body.principal_id, context),
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        status=body.status,
        priority=body.priority,
        notes=body.notes,
        source_json=body.source_json,
        window_id=body.window_id,
    )
    return _deadline_window_out(row)


@router.get("/deadline-windows")
def list_memory_deadline_windows(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[DeadlineWindowOut]:
    rows = container.memory_runtime.list_deadline_windows(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_deadline_window_out(row) for row in rows]


@router.get("/deadline-windows/{window_id}")
def get_memory_deadline_window(
    window_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeadlineWindowOut:
    row = container.memory_runtime.get_deadline_window(
        window_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="deadline_window_not_found")
    return _deadline_window_out(row)
