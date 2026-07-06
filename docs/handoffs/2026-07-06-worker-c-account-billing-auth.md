# Worker C Handoff: Account, Billing, and Auth Surface

Date: 2026-07-06
Lane: `worker`

## Objective

Keep the PropertyQuarry account/billing/auth surfaces calm and consistent:

- account page should use `Billing account`
- account billing links should preserve `run_id` when local
- PropertyQuarry account-nav fallback should prefer `/app/billing`
- no noisy generic Google sync metrics or old automation copy should leak back in

## Current repo truth

The targeted redesign contract slice is green, including the account settings check:

```text
pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'propertyquarry_settings_hide_generic_google_sync_metrics'
```

The focused account and billing browser slice is also green:

```text
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'signed_in_surfaces_prefer_verified_external_billing_handoff_in_live_browser or account_and_billing_hide_redundant_top_actions'
```

Result:

- `2 passed, 82 deselected`

Recent controller-side fixes touched:

- `ea/app/templates/app/_property_account_panel.html`
- `ea/app/api/routes/landing.py`

## Your task

Do a cleanup pass for genericity and hidden regressions around:

- `account_nav.billing_href`
- `/app/account`
- `/app/billing`
- optional Google/account entry copy
- redundant top actions

## Owned files

- `ea/app/templates/app/_property_account_panel.html`
- `ea/app/api/routes/landing.py`
- `ea/app/templates/pricing_page.html`
- related tests only if needed

## Read-only context

- `docs/handoffs/2026-07-06-codex-controller-state.md`
- `tests/test_propertyquarry_workspace_redesign.py`
- `tests/e2e/test_propertyquarry_greenfield_browser.py`

## Forbidden scope

- no changes to the visual-request/tour state machine
- no changes to public-tour playback shell
- no changes to live deployment or external billing provider configuration

## Acceptance tests

Required:

```text
pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'propertyquarry_settings_hide_generic_google_sync_metrics'
pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'signed_in_surfaces_prefer_verified_external_billing_handoff_in_live_browser or account_and_billing_hide_redundant_top_actions'
```

## Stop conditions

- stop once the account/billing/auth surfaces stay green in both contract and browser slices, or once you find a narrower regression with exact file-level evidence

Current stop-state:

- the focused contract and browser checks for this lane are green
- reopen only if a wider regression points back to account, billing, or auth surface truth

## Required receipt

- status
- files changed
- tests run and results
- any remaining hardcoded or non-generic billing/auth assumptions
- controller review needed or not
