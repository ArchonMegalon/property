# Worker B Handoff: Public Tour Playback Shell

Date: 2026-07-06
Lane: `worker`

## Objective

Audit and harden public tour playback so walkthrough opens from PropertyQuarry behave like a polished product surface: direct, reliable, muted-autoplay safe when requested, and free of brittle state gaps between the property page and the tour shell.

## Current repo truth

The walkthrough-open browser journey was failing because the public tour shell loaded the video but did not reliably advance playback after a request-driven open. A controller patch added a stronger autoplay primer in:

- `ea/app/api/routes/public_tours.py`

That exact browser test is now green:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'walkthrough_request_is_user_initiated_in_real_browser'
```

The dedicated public-tour browser suite is also green:

```text
pytest -q tests/e2e/test_propertyquarry_public_tour_browser.py
```

Result:

- `9 passed`

## Your task

Do a second-pass hardening review on the public tour playback path and remove brittle assumptions if any remain.

Focus on:

- walkthrough open URLs like `/tours/<slug>?pane=flythrough-pane&autoplay=1`
- playback start timing
- muted/defaultMuted/autoplay/playsinline behavior
- avoiding regressions between `/tours/<slug>` and `/tours/<slug>/control/<provider>`

## Owned files

- `ea/app/api/routes/public_tours.py`
- related public-tour browser tests if needed

## Read-only context

- `docs/handoffs/2026-07-06-codex-controller-state.md`
- `tests/e2e/test_propertyquarry_greenfield_browser.py`
- `tests/e2e/test_propertyquarry_public_tour_browser.py`

## Forbidden scope

- do not redesign the tour shell visually unless needed for correctness
- do not touch billing/auth/account surfaces
- do not change research/detail request payload contracts

## Acceptance tests

Required:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'walkthrough_request_is_user_initiated_in_real_browser'
```

Recommended:

```text
pytest -q tests/e2e/test_propertyquarry_public_tour_browser.py
```

## Stop conditions

- stop once playback hardening is either proven green or you can show a narrower remaining blocker with exact evidence

Current stop-state:

- the focused walkthrough-open and public-tour playback browser slices are green
- reopen only if a wider e2e or release-gate run exposes a new playback-specific failure

## Required receipt

- status
- files changed
- tests run and results
- any autoplay/browser-policy assumptions still present
- whether more work is needed on the public tour shell
