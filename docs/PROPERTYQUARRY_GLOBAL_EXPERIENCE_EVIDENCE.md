# PropertyQuarry global-experience evidence gate

This gate answers one narrow release question: does the exact PropertyQuarry
build have fresh, independently attested evidence that the AT, DE, and CR
customer experience is launch-ready across language, accessibility, browsers,
devices, field performance, degraded networks, and localized discovery?

The checked-in contract is a definition, not evidence. Running the gate without
a live receipt must produce `status: blocked`. Never convert source assertions,
unit fixtures, mocked browser runs, screenshots, or an operator statement into a
passing live receipt.

## Governed inputs

The source contract is
`config/monitoring/propertyquarry_global_experience.v1.json`. The gate is
`scripts/propertyquarry_global_experience_gate.py`.

A live input must use schema
`propertyquarry.global_experience_live_receipt.v1`, name profile `launch` and
claim scope `core`, include the SHA-256 of the exact source contract, and bind
both its release identity and independent attestation to:

- one exact, lowercase, 40-character Git commit SHA; and
- one immutable image digest in `sha256:<64 lowercase hex>` form.

Every evidence record requires `status: pass`, a timezone-aware `observed_at`, a
content digest in the same SHA-256 form, and an opaque workflow reference. The
gate rejects placeholder-like references. The live receipt, each evidence
record, each approval, the independent attestation, and the end of the field
measurement window must be current within 24 hours. A CLI age override can make
that window shorter, never longer.

The independent release controller must attest the exact commit and image. The
attestation must also name the gate-computed SHA-256 digest of the complete live
payload (excluding the detached attestation object), so changing a market result
after review invalidates the attestation. The attestor must be independent of
implementation, and the attestation artifact must already exist before its
digest or workflow reference is put in the live receipt. Do not ask this script
to manufacture, infer, or fetch it.

## Per-market proof

The live receipt must contain exactly AT (`de-AT`, EUR, `Europe/Vienna`), DE
(`de-DE`, EUR, `Europe/Berlin`), and CR (`es-CR`, CRC,
`America/Costa_Rica`). Each market must provide all of the following:

1. Native-language review by an independently identified reviewer who attests
   native proficiency for the exact market locale and supplies an opaque,
   market-specific qualification reference. The review spans every contracted
   customer route—including public/legal, authentication, account, billing,
   support, and application surfaces—and covers UI and public copy, validation
   messages, formatting, regional address conventions, and text
   expansion/layout.
2. Automated WCAG 2.2 AA evidence on Chromium, Firefox, and WebKit over every
   contracted customer route family, with the contracted WCAG tags and no
   serious or critical violations. The 39-family set includes public, legal,
   authentication, discovery, agents/alerts, shortlist/run detail, research
   detail, packets, account/billing/support, every customer settings surface,
   notification preview, and the first-party tour shell. A parameterized family
   must be exercised with a real governed fixture, not the literal braces.
3. Manual pass evidence for keyboard navigation, desktop and mobile screen
   readers, 200% and 400% zoom, and reduced motion. The screen-reader matrix is
   NVDA/Windows, VoiceOver/macOS, VoiceOver/iOS, and TalkBack/Android.
4. Functional desktop coverage on Chromium, Firefox, and WebKit with an exact
   browser version, binary digest, and execution-environment reference. Mobile
   coverage must use physical devices—not viewport emulation—for the contracted
   390×844 iOS Safari and 412×915 Android Chrome profiles, recording browser and
   OS versions, device model, and governed device-lab reference.
5. Field RUM at p75 over a window of at least 28 days and at least 200 samples
   in each of the desktop and mobile cohorts for each market. LCP must be at
   most 2500 ms, INP at most 200 ms, and CLS at most 0.1 in both cohorts. An
   aggregate that hides a failing device cohort, lab runs, and synthetic
   fixtures cannot substitute for this field evidence.
6. Recovery evidence for slow 3G, offline reconnect, packet-loss retry, and
   request-timeout recovery, proving recovery without data loss or duplicate
   mutation.
7. Localized SEO evidence for the exact `html lang` and `Content-Language`, a
   self-canonical URL, reciprocal `de-AT`, `de-DE`, `es-CR`, and `x-default`
   hreflang, localized metadata, sitemap membership, and indexable robots
   posture.
8. Fresh state evidence for successful and failed authentication, expired-session
   recovery, ready and unavailable billing handoff, HTTP 401/403/404/422/429/500/503,
   and first-party-tour ready, unavailable, and revoked behavior. Every state
   must preserve accepted customer data and expose a useful next action; the
   same states are included in native review and automated, manual, desktop, and
   physical-mobile coverage.

The receipt also requires fresh approvals from the global-experience,
accessibility, localization, performance, and SEO owners. An approval is not a
substitute for its underlying evidence.

## Operator sequence

1. Freeze the candidate commit and immutable image digest.
2. Have the named evidence owners execute the contract against that exact
   candidate in the governed environment. Keep raw reports outside Git and
   record only their immutable digest and opaque workflow reference.
3. Have the independent release controller verify the receipt, source-contract
   digest, evidence currency, and exact release binding, then issue the
   attestation.
4. Evaluate without editing the receipt:

   ```bash
   python3 scripts/propertyquarry_global_experience_gate.py \
     --live-receipt /governed/receipts/propertyquarry-global-experience-live.json \
     --expected-commit 0123456789abcdef0123456789abcdef01234567 \
     --expected-image sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
     --output /governed/receipts/propertyquarry-global-experience-gate.json \
     --fail-on-blocked
   ```

5. Supply the generated gate receipt to Gold with
   `--global-experience-receipt`. Launch/Core must block unless this receipt
   passes. Standard and flagship profiles only surface its health and do not
   gain a launch claim from it.

The example command demonstrates argument shape only; its identities are not
evidence and must not be copied into a live receipt.

## Fail-closed handling

Treat every item in `blockers` as unresolved. Do not delete an unavailable
market, lower thresholds, widen freshness, relabel synthetic data as field RUM,
or substitute one browser or assistive technology for another. Regenerate the
affected evidence for the same candidate, obtain a new independent attestation,
and rerun the gate.

At source-only state the exact blocker is intentionally the absent governed live
receipt. No repository artifact establishes native UI/content review, manual
assistive-technology coverage, tri-engine and mobile-device coverage, field CWV
samples, degraded-network recovery, localized SEO, approvals, or independent
release attestation for a deployable image. Therefore the checked-in state is
not a global launch claim.
