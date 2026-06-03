from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class FollowUpIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    stakeholder_ref: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    status: str = Field(default="open", max_length=80)
    due_at: str | None = Field(default=None, max_length=80)
    channel_hint: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    follow_up_id: str | None = Field(default=None, max_length=200)


class FollowUpOut(BaseModel):
    follow_up_id: str
    principal_id: str
    stakeholder_ref: str
    topic: str
    status: str
    due_at: str | None
    channel_hint: str
    notes: str
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class FollowUpRuleIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    trigger_kind: str = Field(min_length=1, max_length=120)
    channel_scope: list[str] = Field(default_factory=list)
    delay_minutes: int = Field(default=60, ge=0, le=10080)
    max_attempts: int = Field(default=3, ge=1, le=20)
    escalation_policy: str = Field(default="notify_exec", max_length=200)
    conditions_json: dict[str, object] = Field(default_factory=dict)
    action_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="active", max_length=80)
    notes: str = Field(default="", max_length=5000)
    rule_id: str | None = Field(default=None, max_length=200)


class FollowUpRuleOut(BaseModel):
    rule_id: str
    principal_id: str
    name: str
    trigger_kind: str
    channel_scope: list[str]
    delay_minutes: int
    max_attempts: int
    escalation_policy: str
    conditions_json: dict[str, object]
    action_json: dict[str, object]
    status: str
    notes: str
    created_at: str
    updated_at: str


def _follow_up_out(row) -> FollowUpOut:  # type: ignore[no-untyped-def]
    return FollowUpOut(
        follow_up_id=row.follow_up_id,
        principal_id=row.principal_id,
        stakeholder_ref=row.stakeholder_ref,
        topic=row.topic,
        status=row.status,
        due_at=row.due_at,
        channel_hint=row.channel_hint,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _follow_up_rule_out(row) -> FollowUpRuleOut:  # type: ignore[no-untyped-def]
    return FollowUpRuleOut(
        rule_id=row.rule_id,
        principal_id=row.principal_id,
        name=row.name,
        trigger_kind=row.trigger_kind,
        channel_scope=list(row.channel_scope),
        delay_minutes=row.delay_minutes,
        max_attempts=row.max_attempts,
        escalation_policy=row.escalation_policy,
        conditions_json=row.conditions_json,
        action_json=row.action_json,
        status=row.status,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/follow-ups")
def upsert_memory_follow_up(
    body: FollowUpIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FollowUpOut:
    row = container.memory_runtime.upsert_follow_up(
        principal_id=resolve_principal_id(body.principal_id, context),
        stakeholder_ref=body.stakeholder_ref,
        topic=body.topic,
        status=body.status,
        due_at=body.due_at,
        channel_hint=body.channel_hint,
        notes=body.notes,
        source_json=body.source_json,
        follow_up_id=body.follow_up_id,
    )
    return _follow_up_out(row)


@router.get("/follow-ups")
def list_memory_follow_ups(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[FollowUpOut]:
    rows = container.memory_runtime.list_follow_ups(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_follow_up_out(row) for row in rows]


@router.get("/follow-ups/{follow_up_id}")
def get_memory_follow_up(
    follow_up_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FollowUpOut:
    row = container.memory_runtime.get_follow_up(
        follow_up_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="follow_up_not_found")
    return _follow_up_out(row)


@router.post("/follow-up-rules")
def upsert_memory_follow_up_rule(
    body: FollowUpRuleIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FollowUpRuleOut:
    row = container.memory_runtime.upsert_follow_up_rule(
        principal_id=resolve_principal_id(body.principal_id, context),
        name=body.name,
        trigger_kind=body.trigger_kind,
        channel_scope=tuple(body.channel_scope),
        delay_minutes=body.delay_minutes,
        max_attempts=body.max_attempts,
        escalation_policy=body.escalation_policy,
        conditions_json=body.conditions_json,
        action_json=body.action_json,
        status=body.status,
        notes=body.notes,
        rule_id=body.rule_id,
    )
    return _follow_up_rule_out(row)


@router.get("/follow-up-rules")
def list_memory_follow_up_rules(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[FollowUpRuleOut]:
    rows = container.memory_runtime.list_follow_up_rules(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_follow_up_rule_out(row) for row in rows]


@router.get("/follow-up-rules/{rule_id}")
def get_memory_follow_up_rule(
    rule_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FollowUpRuleOut:
    row = container.memory_runtime.get_follow_up_rule(
        rule_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="follow_up_rule_not_found")
    return _follow_up_rule_out(row)
