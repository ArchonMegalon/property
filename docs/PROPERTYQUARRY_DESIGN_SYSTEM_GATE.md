# PropertyQuarry Design System Gate

The design gate protects the customer-facing product loop:

```text
Brief -> Search -> Compare -> Dossier -> Tour -> Decide -> Explain why -> Learn
```

The detailed pixel/layout contract lives in:

```text
docs/PROPERTYQUARRY_APP_LAYOUT_GUIDE.md
```

The stricter premium release bar lives in:

```text
docs/PROPERTYQUARRY_PREMIUM_UI_EXIT_GATE.md
```

When a UI change conflicts with a local template habit, the app layout guide wins unless the product owner explicitly approves a new pattern.
When a UI change technically works but feels noisy, cramped, fake, or tool-like, the premium UI exit gate wins.

## Customer Surface Rules

```text
no raw URLs shown as labels
no plaintext URLs in Telegram or email body text
no legacy EA wording on customer surfaces
no OODA/operator jargon on customer surfaces
no clipped setup or review tiles
all CTAs have human labels
mobile hit targets are at least 44px where browser-tested
empty states explain the next action
diagnostics stay behind operator/admin surfaces
```

## Results Page Rules

```text
rank best fit to worst fit
show why each result was selected
show direct map/navigation as titled action
show suppressed-candidate summaries
offer rule relaxation when one filter blocks otherwise strong matches
```

## Search Agent Rules

```text
show what the agent watches
show cadence and next run
show notification budget per day/week
show sent vs suppressed results
show why a property was hidden
allow pause, resume, edit, duplicate, delete
```
