from __future__ import annotations

import pytest

from app.domain.models import (
    IntentSpecV3,
    PlanSpec,
    PlanStepSpec,
    PlanValidationError,
    TaskExecutionRequest,
    now_utc_iso,
    validate_plan_spec,
)
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.services.orchestrator import RewriteOrchestrator


def _plan(*steps: PlanStepSpec) -> PlanSpec:
    return PlanSpec(
        plan_id="plan-1",
        task_key="rewrite_text",
        principal_id="exec-1",
        created_at=now_utc_iso(),
        steps=steps,
    )


def _step(step_key: str, *, depends_on: tuple[str, ...] = ()) -> PlanStepSpec:
    return PlanStepSpec(
        step_key=step_key,
        step_kind="system_task",
        tool_name="",
        evidence_required=(),
        approval_required=False,
        reversible=False,
        expected_artifact="",
        fallback="fail",
        depends_on=depends_on,
    )


def test_validate_plan_spec_rejects_unknown_dependency_keys() -> None:
    plan = _plan(
        _step("step_input_prepare"),
        _step("step_policy_evaluate", depends_on=("step_missing",)),
    )

    with pytest.raises(PlanValidationError, match="unknown_dependency:step_policy_evaluate:step_missing"):
        validate_plan_spec(plan)


def test_validate_plan_spec_rejects_duplicate_step_keys() -> None:
    plan = _plan(
        _step("step_input_prepare"),
        _step("step_input_prepare"),
    )

    with pytest.raises(PlanValidationError, match="duplicate_step_key:step_input_prepare"):
        validate_plan_spec(plan)


def test_validate_plan_spec_rejects_dependency_cycles() -> None:
    plan = _plan(
        _step("step_input_prepare", depends_on=("step_artifact_save",)),
        _step("step_artifact_save", depends_on=("step_input_prepare",)),
    )

    with pytest.raises(PlanValidationError, match="dependency_cycle:step_input_prepare"):
        validate_plan_spec(plan)


class _InvalidPlanner:
    def build_plan(self, *, task_key: str, principal_id: str, goal: str):
        intent = IntentSpecV3(
            principal_id=principal_id,
            goal=goal,
            task_type=task_key,
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
            desired_artifact="rewrite_note",
        )
        plan = _plan(
            _step("step_input_prepare"),
            _step("step_policy_evaluate", depends_on=("step_missing",)),
        )
        return intent, plan


def test_orchestrator_rejects_invalid_plans_before_starting_a_session() -> None:
    ledger = InMemoryExecutionLedgerRepository()
    orchestrator = RewriteOrchestrator(
        artifacts=InMemoryArtifactRepository(),
        ledger=ledger,
        planner=_InvalidPlanner(),
    )

    with pytest.raises(PlanValidationError, match="unknown_dependency:step_policy_evaluate:step_missing"):
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="rewrite_text",
                text="Scope-safe validation.",
                principal_id="exec-1",
                goal="rewrite this",
            )
        )

    assert ledger._sessions == {}
