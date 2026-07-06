# Worker A Handoff: Visual Request State Machine

Date: 2026-07-06
Lane: `worker`

## Objective

Fix the browser-visible visual-request state machine so a ready 3D tour stays visibly ready even while a walkthrough is queued, and so research/detail surfaces keep or restore the freshest state after request-driven navigation instead of falling back to stale queued or idle copy.

## Current repo truth

The original blocker is resolved. This browser test is now green:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'
```

Result:

- `1 passed, 83 deselected`

The hosted-tour return-path regression is also resolved:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser'
```

Result:

- `1 passed, 83 deselected`

Resolved root cause:

- walkthrough readiness was inferred too loosely from generic hosted tour URLs
- that let a ready 3D tour URL masquerade as a ready walkthrough URL
- once the false ready state was removed, queued walkthrough polling also needed to be restarted from synchronized state instead of only from the click handler
- hosted-tour back navigation could recreate the packet with default idle buttons before the `pageshow` resync path restored the ready state
- research detail now remembers the last non-idle visual button state locally, restores it on reload/return, and then verifies it with the normal visual-status refresh

## Files touched

- `ea/app/templates/app/property_research_detail.html`
- `ea/app/templates/app/object_detail.html`
- `ea/app/templates/app/_property_workbench_script.html`

- `ea/app/templates/app/property_research_detail.html`
- `ea/app/templates/app/object_detail.html`
- `ea/app/templates/app/_property_workbench_script.html`

Behavior now enforced:

- only explicit walkthrough targets count as walkthrough-ready
- a queued walkthrough no longer downgrades a ready 3D tour in the visual rail
- queued walkthrough polling continues in the background while the rail prefers the ready tour
- a ready 3D-tour button survives hosted-tour navigation and stays visible again when the user comes back to the research packet

## Read-only context

- `docs/handoffs/2026-07-06-codex-controller-state.md`
- `ea/app/api/routes/landing_property_workspace_payload.py`
- `tests/e2e/test_propertyquarry_greenfield_browser.py`

## Forbidden scope

- no billing/auth nav changes unless strictly required
- no public-tour HTML redesign outside the state-machine behavior
- no broad copy rewrites unrelated to the failing behavior

## Acceptance tests

Required:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser'
```

Keep green:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'walkthrough_request_is_user_initiated_in_real_browser'
pytest -x -q tests/test_propertyquarry_workspace_redesign.py -k "billing or sign_in or google or auth or research or inline or visual or walkthrough or tour"
```

## Acceptance tests run

- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'`
- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser'`
- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser or propertyquarry_walkthrough_request_is_user_initiated_in_real_browser or propertyquarry_visual_request_does_not_invent_eta_before_backend_supplies_one or propertyquarry_blocked_3d_tour_can_be_retried_from_research_packet_in_real_browser or propertyquarry_ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'`
- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'walkthrough_request_is_user_initiated_in_real_browser or ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'`
- `pytest -x -q tests/test_propertyquarry_workspace_redesign.py -k "billing or sign_in or google or auth or research or inline or visual or walkthrough or tour"`

## Remaining status

- no open blocker is currently recorded in this lane
- next continuation should only reopen this area if a wider release-gate or browser slice fails with new evidence
