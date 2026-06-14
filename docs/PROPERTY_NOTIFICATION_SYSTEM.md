# Property Notification System

## Goal

PropertyQuarry notifications are decision surfaces, not generic status mail.

Each property-facing template must help the user do one of these next actions:

- open property page
- open hosted 360
- ask the agent for missing facts
- record `yes`, `maybe`, or `no`
- explain blockers

## Templates

- `search_results_ready`
- `property_match`
- `tour_ready`
- `investment_research_ready`
- `external_feedback_received`
- `workspace_invite`
- `access_link`
- `google_connect`

## Renderer boundary

Renderer selection must stay adapterized:

- `inline_html`
- `markup2go`
- future optional renderers such as `mjml`

The renderer contract is:

```python
class EmailTemplateRenderer(Protocol):
    def render(self, template_key: str, payload: dict[str, object]) -> RenderedEmail:
        ...
```

## Required output

Every customer-facing template must provide:

- subject
- preheader
- html body
- plain-text body
- primary CTA
- mobile-safe buttons

## Brand rules

- no customer-facing PropertyQuarry email may say `EA prepared`
- CTA labels must be action-first
- HTML must stay address-safe and token-safe
- plain text must include every critical URL present in HTML

## Property decision CTA model

High-value property notifications should support:

- `Open property page`
- `Open 360`
- `Yes, shortlist`
- `Maybe, keep watching`
- `No, reject`
- `Ask agent`

Email-triggered decision links should write a pending event first and require in-app confirmation before permanent learning.

## Preview and test requirements

- authenticated preview route
- fixture-backed preview page
- snapshot coverage for key property templates
- contract tests for:
  - no `EA` branding
  - escaped URLs
  - preheader presence
  - plain-text fallback completeness
  - renderer fallback behavior
