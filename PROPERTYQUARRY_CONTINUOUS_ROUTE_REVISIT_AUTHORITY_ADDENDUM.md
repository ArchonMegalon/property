# PropertyQuarry Continuous Route Revisit Authority Addendum

Date: 2026-07-11 (Europe/Vienna)

State: `revision_2_proposed_for_fresh_independent_review`

Parent authority SHA-256:
`401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a`

Implementation state: `blocked_pending_accept`

## Product decision

PropertyQuarry owns room identity, portal truth, walkability, route priority,
revisit policy, and public product meaning. A flagship apartment walkthrough
must be one continuous camera journey that enters every source-classified
walkable room. It must not omit a branch room or use a cut, teleport, scene
jump, or fabricated doorway when a hall must be revisited.

The accepted R9 unique-route restriction is insufficient for common apartment
graphs. PropertyQuarry therefore proposes the bounded route semantics in:

`/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_10_CONTINUOUS_ROUTE_REVISIT_AMENDMENT.md`

## Product contract behavior

The Property-owned contract name remains
`propertyquarry.governed_spatial_tour_input.v1`.

Version `1.0.0` remains accepted with its current exact allowlist and current
meaning. It requires `route_room_ids` as the unique explicit final route,
emits no revisit, and rejects the new fields below.

Version `1.1.0` is the exact backward-compatible minor version. Its exact
allowlist removes `route_room_ids` and adds these required fields:

```text
route_priority_room_ids
route_start_room_id
```

`route_priority_room_ids` is a nonempty unique list whose set equals every
source-classified walkable room. `route_start_room_id` must equal its first
item. Version `1.1.0` rejects legacy `route_room_ids`; version `1.0.0` rejects
the priority and start fields. A union allowlist or inferred version is
forbidden.

This version split distinguishes:

- a unique first-visit room priority supplied by verified first-party property
  truth; and
- the expanded ordered visit sequence sent to the shared generic contract.

The bridge derives the visit sequence deterministically from verified rooms and
walkable portals. It may insert only rooms already classified walkable and only
transitions backed by a source portal. It fails closed on disconnected or
incoherent geometry.

The planner output is bounded to `2N-1` room visits, contains no consecutive
duplicate, covers the exact walkable set, and is emitted identically in the
request and source packet. `allow_revisit` reflects the actual output rather
than caller preference.

Planner adjacency ordering uses first-visit priority and then stable room
token, so room, portal, cyclic-edge, and cross-edge input permutations cannot
change the output. Duplicate portal identities and self-portals fail closed.
Multiple differently identified doors between the same rooms may exist but
collapse to one adjacency relation for route planning.

An endpoint-start linear path may require no revisit. An interior-start linear
path may correctly revisit an intermediate room; `B, A, B, C` is valid for
path `A-B-C`.

## Privacy and ownership

This addendum does not change source, consent, rights, publication, retention,
deletion, legal-hold, or owner-scope authority. It does not permit exact
location, identity, provider data, credentials, private refs, or live property
records in tests or review.

EA may implement the provider-neutral machinery only after independent design
acceptance. EA does not own the route, source truth, product projection,
publication, readiness, or promotion. Chummer may reuse the generic revisit
contract for runsite walkthroughs but cannot change PropertyQuarry route truth.

## Required product proof

Local implementation acceptance requires synthetic tests for linear, hub,
branching, disconnected, reverse-portal, full-coverage, bounded-revisit,
input-permutation, cyclic/cross-edge, `2N-1` boundary, malformed priority,
start mismatch, self-portal, duplicate portal identity, old/new version,
idempotency, and privacy-safe projection cases. Real flagship acceptance still
requires a generated continuous walkthrough, frame and transform analysis,
human review, desktop/mobile/accessibility verification, current provider
evidence, deletion proof, and a clean 48-hour canary.

## Decision ceiling

This candidate authorizes no implementation until a fresh independent reviewer
accepts its exact hash together with the Revision 10 amendment. It authorizes
no provider use, quota burn, browser run, render, video delivery, deployment,
publication, promotion, or readiness claim.
