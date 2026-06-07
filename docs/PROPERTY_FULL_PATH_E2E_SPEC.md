# Property Full-Path E2E Spec

## Objective

The flagship PropertyQuarry proof is not “search ran”.

It is:

`brief -> provider scan -> shortlist -> packet -> 360 -> decision -> follow-up -> learning`

## Required fixture path

The required deterministic browser path is:

1. open `/app/properties`
2. load a seeded run
3. open a selected shortlist candidate
4. save a decision
5. open `Clippy`
6. record an `Ask agent` follow-up
7. verify the follow-up appears in the workbench
8. open the packet
9. update the follow-up lifecycle
10. verify the updated state returns to the workbench
11. verify household review, risk signals, and timeline remain visible

## Covered browser gates

The browser suite should collectively prove:

- mobile usability
- shortlist to packet flow
- packet share and republish flow
- feedback review queue flow
- optimization acknowledgement flow
- decision to follow-up continuity flow

## Future required expansions

Add explicit fixture-backed proofs for:

- all-provider entitlement bypass
- underwriting packet review
- signed email decision actions
- aggregate-risk suppression and publication thresholds
- provider-quality dashboard state

## Release gate requirement

This flow must stay inside `scripts/property_release_gates.sh`.

If the browser flow fails, the release bundle is not green.
