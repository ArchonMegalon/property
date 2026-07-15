from __future__ import annotations

from typing import Callable

import pytest

from app.domain.models import ExecutionEvent, HumanTask, now_utc_iso
from app.repositories.human_tasks import InMemoryHumanTaskRepository
from app.services.human_task_routing_runtime_service import HumanTaskRoutingService
from app.services.operator_task_routing_service import OperatorTaskRoutingService


def _task_repository() -> tuple[InMemoryHumanTaskRepository, HumanTask]:
    repository = InMemoryHumanTaskRepository()
    task = repository.create(
        session_id="session-1",
        step_id="step-1",
        principal_id="principal-1",
        task_type="review",
        role_required="reviewer",
        brief="Review this output",
    )
    return repository, task


def _routing_service(
    repository: InMemoryHumanTaskRepository,
) -> tuple[OperatorTaskRoutingService, list[ExecutionEvent]]:
    events: list[ExecutionEvent] = []

    def append_event(session_id: str, name: str, payload: dict[str, object]) -> ExecutionEvent:
        event = ExecutionEvent(
            event_id=f"event-{len(events) + 1}",
            session_id=session_id,
            name=name,
            payload=dict(payload),
            created_at=now_utc_iso(),
        )
        events.append(event)
        return event

    human_task_routing = HumanTaskRoutingService(
        list_profiles_for_principal=lambda **_kwargs: [],
        fetch_session_events=lambda session_id: [
            event for event in events if event.session_id == session_id
        ],
    )
    service = OperatorTaskRoutingService(
        fetch_human_task=repository.get,
        claim_human_task=repository.claim,
        assign_human_task=repository.assign,
        append_event=append_event,
        decorate_human_task=human_task_routing.decorate_human_task,
    )
    return service, events


@pytest.mark.parametrize(
    ("transition", "expected_event", "expected_state", "expected_source"),
    [
        ("claim", "human_task_claimed", "claimed", "manual"),
        ("assign", "human_task_assigned", "assigned", "manual"),
    ],
)
def test_claim_and_assign_return_fresh_transition_summary(
    transition: str,
    expected_event: str,
    expected_state: str,
    expected_source: str,
) -> None:
    repository, task = _task_repository()
    service, events = _routing_service(repository)
    action: Callable[..., HumanTask | None]
    if transition == "claim":
        action = service.claim_human_task
        updated = action(
            task.human_task_id,
            principal_id=task.principal_id,
            operator_id="operator-1",
            assigned_by_actor_id="operator-admin",
        )
    else:
        action = service.assign_human_task
        updated = action(
            task.human_task_id,
            principal_id=task.principal_id,
            operator_id="operator-1",
            assignment_source="manual",
            assigned_by_actor_id="operator-admin",
        )

    assert updated is not None
    assert len(events) == 1
    assert updated.last_transition_event_name == expected_event
    assert updated.last_transition_at == events[0].created_at
    assert updated.last_transition_assignment_state == expected_state
    assert updated.last_transition_operator_id == "operator-1"
    assert updated.last_transition_assignment_source == expected_source
    assert updated.last_transition_by_actor_id == "operator-admin"
