# PropertyQuarry incident and support operations

This runbook owns the human operating loop around the alert-specific procedures
in `PROPERTYQUARRY_SLO_ALERT_RUNBOOK.md`. The machine-readable authority is
`config/monitoring/propertyquarry_incident_support.v1.json`.

Source policy is not proof of live coverage. A launch remains blocked until the
incident/support gate verifies an exact-release, fresh receipt from the
independent release authority containing real primary and backup role assignments,
staffed support windows for AT, DE, and CR in each market's governed timezone and
native launch language plus English, configured private endpoints, completed
drills, owner approvals, and a verified attestation. Every drill, approval, and
attestation record must be current within the governed 24-hour receipt window and
carry an immutable digest and opaque workflow reference. The detached independent
attestation binds the complete asserted payload digest, so post-review edits fail
closed. Names, contact
details, customer data, credentials, and webhook URLs must not be committed to
the repository.

## Declare and take control

1. Preserve the alert payload, evaluation time, release SHA and image digest,
   `/version`, readiness reason, metrics snapshot, bounded correlation IDs, and
   relevant immutable receipts before changing state.
2. Page the primary and backup rotation. The first responder declares severity
   from the governed definitions and opens the private incident record.
3. Assign an incident commander within the severity clock. The commander owns
   decisions and cadence; operations, communications, support, and
   security/privacy leads own their named workstreams.
4. Contain the smallest reversible surface. Never hide an alert, raise a
   threshold, erase evidence, bypass a safeguard, rotate credentials, buy quota,
   or activate a provider without the authority that action requires.

## Communicate

- The communications lead posts the first customer-safe status update within the
  governed clock and continues at or faster than the required cadence. State
  observed impact and current action; do not speculate, expose private details,
  or promise an unverified recovery time.
- Support links related cases to the incident without copying secrets or excess
  personal data. P0/P1 cases page the on-call lane immediately; lower priorities
  follow the governed escalation map.
- Each launch market must have a declared timezone, languages, staffed window,
  primary owner, and backup. An unstaffed market cannot remain launch-supported.

## Security and privacy

The security/privacy lead starts an internal breach assessment within 24 hours
for suspected unauthorized access, disclosure, alteration, loss, or unavailable
personal data. The 72-hour regulatory clock in the contract is a maximum
notification clock where applicable; it does not replace controller/legal
assessment or create a blanket reporting rule. Preserve the minimum necessary
evidence and keep credentials and unnecessary personal data out of incident and
support systems.

## Recover and close

Use the named recovery, rollback, database, provider, and delivery runbooks. A
service restart is not recovery proof. Before closure, re-prove readiness,
required heartbeats, alert delivery, immutable release identity, affected customer
journeys, and any required data reconciliation. Record customer impact, the
decision timeline, follow-up owner and due date, and regulatory/customer follow-up.
SEV0-SEV2 incidents require a blameless postmortem within five business days.

## Launch evidence

Run:

```bash
python3 scripts/propertyquarry_incident_support_gate.py \
  --live-receipt /protected/incident-support-live.json \
  --expected-release-sha "$RELEASE_SHA" \
  --expected-image-digest "$IMAGE_DIGEST" \
  --required-market AT \
  --required-market DE \
  --required-market CR \
  --fail-on-blocked
```

The verifier checks structure, freshness, identity, contract digest, market
coverage, roles, endpoint classes, drill evidence, approvals, and independent
attestation. The market list cannot be narrowed and the freshness override can
only make the 24-hour policy stricter. It does not assign people, contact them,
configure services, or make legal decisions.
