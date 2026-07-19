# PropertyQuarry jurisdiction, privacy, residency, and provider-rights gate

This gate answers one narrow launch question: is there current, independently
attested authority to operate the exact PropertyQuarry release and its exact
provider capability set in Austria, Germany, and Costa Rica?

The checked-in source contract defines what evidence is required. It is not
legal advice, a legal conclusion, provider permission, or launch approval. With
no live receipt, the gate must remain `blocked`.

## Required live evidence

For each of AT, DE, and CR, the live receipt must bind to the current market
envelope, exact 40-character Git SHA, and immutable `sha256:` image digest. It
must include localized live privacy, cookie, terms, and DSAR URLs; controller
identity; hosting, backup, logging, and support residency decisions; every
required privacy and consumer control; and a current approval from an
independent, qualified local reviewer. Approval records expire after at most
400 days and cannot be future-dated.

Provider evidence is capability-specific. The receipt inventories every launch
provider by market and states which governed capabilities are enabled. A
current terms-and-rights review must partition every capability into permitted
or prohibited. Enabled capabilities must be permitted, while prohibited
capabilities need exact technical-enforcement proof. This prevents a general
provider approval from silently authorizing media storage, derivative
generation, or public republication.

An independent compliance controller must attest the complete receipt for the
same commit and image. Placeholder people, approvals, endpoints, and reserved
domains are rejected.

## Operator command

```bash
scripts/propertyquarry_jurisdiction_privacy_rights_gate.py \
  --live-receipt /protected/path/jurisdiction-rights-live.json \
  --expected-release-sha "$PROPERTYQUARRY_RELEASE_COMMIT_SHA" \
  --expected-image-digest "$PROPERTYQUARRY_RELEASE_IMAGE_DIGEST" \
  --output _completion/property_jurisdiction_privacy_rights/release-gate.json \
  --fail-on-blocked
```

The output is launch evidence only when `status` is `pass`. A source-contract
pass, private-beta posture, locally authored receipt, or receipt for another
candidate has no launch authority.
