# PropertyQuarry Data Retention

PropertyQuarry handles property facts, private packets, Telegram events, tour assets, MagicFit references, Dadan videos, signed links, and operator projections. Retention must be explicit because the product loop learns from decisions without turning every raw artifact into permanent memory.

## Default Rules

```text
personal reference images expire unless pinned by the owner
Dadan recordings remain external untrusted links until owner review
private PDFs and signed packet links must be revocable
Telegram metadata is retained only as needed for delivery receipts and decision history
Teable projections are derived views and must be deletable from the PropertyQuarry source record
public tour assets can outlive the private packet only when privacy mode allows publication
raw provider diagnostics stay operator-only
```

## Delete / Revoke Actions

```text
delete private MagicFit reference media
revoke signed PDF or packet links
remove a Dadan response from owner-review queues
delete or pause a search agent
remove Teable projection rows by source property record
export/delete owner decision history on account request
```

## Product Contract

```text
private media is never sent to public analytics
raw household feedback is owner-private by default
public market intelligence uses aggregate reason keys, not raw notes
document intake records carry privacy class and redaction state
```

