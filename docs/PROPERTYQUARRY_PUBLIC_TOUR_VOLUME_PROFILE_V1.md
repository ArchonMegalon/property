# PropertyQuarry public-tour volume profile v1

Status: repository-owned production-controller profile. This profile is an
obligation of the independently installed PropertyQuarry release controller;
it is not release authority, a privileged implementation, or an extension of
the release-control protocol-v1 wire schema.

## Closed profile and signed binding

The profile identifier is
`propertyquarry.public-tour-volume-profile.v1`. The installed controller must
reject an unsupported identifier, version, field, operation, or behavior. A
future extension requires a new profile version.

The root-owned canonical Compose plan must contain this complete profile. The
signed release request already binds the SHA-256 digest of that exact plan as
`release.policy_digests.canonical_compose_plan`; the controller must securely
open the authority-owned plan and require equality with both the request and
its own root-owned controller manifest. Candidate-controlled files, environment
variables, Compose substitutions, and command-line values must not select or
override the volume, mount target, repair identities, evidence destinations, or
policy.

Protocol-v1 conformance alone does not prove this profile was enforced. The
trusted controller and its signed, content-addressed evidence provide that
runtime proof.

## Canonical volume binding

The only conformant public-tour volume binding is:

| Property | Required value |
| --- | --- |
| Logical purpose | `public-tours` |
| Application setting | `EA_PUBLIC_TOUR_DIR` |
| Application setting value | `/data/public_property_tours` |
| Container mount target | `/data/public_property_tours` |
| Storage kind | Docker named volume |
| Docker volume name | `property_propertyquarry_public_tours` |
| Compose lifecycle | externally managed; never candidate-project scoped |
| Access | read-write only where the canonical plan authorizes it |
| Runtime UID:GID | `10001:10001` |
| Repairable legacy UID:GID | exactly `1000:1000` |

Before a preflight can report `ready`, and again under the release lock before
any run mutation, the controller must derive the volume and container mount
facts from the Docker daemon. It must verify the exact volume name, the mount
source, the exact container destination, and the volume-root device/inode
identity. The live and candidate application must mount the same canonical
volume. A newly created, empty, project-prefixed, copied, restored, seeded, or
otherwise substitute volume must fail closed. Candidate data must never be
copied over or merged into the canonical volume as part of this profile.
Candidate validation must mount the canonical volume read-only unless the
controller has entered a separately fenced, policy-authorized, and journaled
write phase after candidate containment.

Deleting, pruning, recreating, relabeling, or changing the driver of the
canonical volume is forbidden. A same-named volume whose stable root identity
changes during an operation is a different volume and must fail closed.

## Stable-root traversal

The controller must open the Docker-derived canonical volume root before
enumeration and retain that stable root file descriptor through manifesting,
repair, verification, and any rollback. Every descendant operation must be
relative to that descriptor and must enforce all of the following:

- resolution remains beneath the stable root;
- symbolic links and magic links are never followed;
- traversal never crosses a device or nested mount boundary;
- the device/inode identity observed before mutation still identifies the
  object being mutated; and
- unsupported file types, identity drift, lookup races, or unavailable secure
  traversal primitives fail closed.

Symbolic links may be inventoried using no-follow metadata and their literal
target bytes, but they are never traversal paths. Ownership repair is limited
to regular files and directories. No relative path supplied by a candidate,
manifest, or directory entry may escape or replace the stable root.

## Preflight and manifests

Preflight is strictly read-only. It may inventory and report a bounded,
policy-authorized ownership repair, but it must not contain, journal, chown,
chmod, start or replace a container, or otherwise mutate the volume. A `ready`
preflight must include passing checks with these exact IDs:

- `public-tour.volume-identity`
- `public-tour.inventory`
- `public-tour.ownership-plan`
- `public-tour.rollback-plan`

A run must acquire the controller's release lock, perform the protocol-required
containment, and then create a fresh pre-mutation manifest before its first
volume mutation. Pre- and post-mutation manifests are closed, canonical JSON
documents. They contain exactly the fields fixed by the root-owned plan, with
no unknown properties; that closed field set must include:

- profile identifier and version, phase, and observation time;
- Docker volume name, container target, and stable root device/inode identity;
- entry count and total regular-file bytes;
- a content-tree SHA-256 covering relative path bytes, node type, regular-file
  bytes, and literal symbolic-link target bytes;
- a mode-tree SHA-256 covering relative path bytes, node type, and mode bits;
- an ownership-tree SHA-256 and bounded UID:GID histogram; and
- the count of exact `1000:1000` repair candidates and unexpected ownerships.

Canonical ordering, path encoding, hashing, integer bounds, and supported node
types must be fixed by the root-owned plan. Unsupported or unrepresentable
entries fail closed; they must not be silently omitted.

The post-mutation entry count, total regular-file bytes, content-tree digest,
and mode-tree digest must exactly equal their pre-mutation values. The only
permitted ownership-tree difference is the exact set recorded in the durable
ownership journal.

## Ownership-only repair

The repair is optional when no legacy entries exist and otherwise consists only
of changing an exact `1000:1000` regular file or directory to `10001:10001`.
The controller must not change an entry with a mixed owner, any other UID or
GID, an unexpected type, or identity drift. Such an entry may remain untouched
only when it is already valid under the closed plan; otherwise the operation
fails closed for operator review.

Before the first ownership change, the controller must durably write and fsync
a content-addressed journal containing every planned relative path, node type,
device/inode identity, original UID:GID, target UID:GID, and original mode. Each
entry must be revalidated immediately before and after a no-follow ownership
operation.

The controller must not write file content, rename, create, delete, truncate,
or change mode bits, ACLs, extended attributes, or link targets. `chmod`, and in
particular any world-writable mode such as `0777`, is forbidden. Because an
ownership change can clear set-ID bits on some systems, a repair candidate with
setuid or setgid mode bits must fail closed instead of restoring those bits with
`chmod`.

## Rollback

The ownership journal must be sufficient to reverse every completed ownership
change without recursive or path-wide mutation. If a run fails after the first
ownership change, the controller must choose and verify exactly one of these
policy-authorized terminal states:

1. restore each journaled entry to its original UID:GID and verify the original
   content, mode, ownership, count, and stable-root identities; or
2. retain the ownership-only repair only after proving that the rollback image
   is bound to runtime `10001:10001`, mounts the same canonical volume, can read
   the affected paths, and preserves the pre-mutation content and modes.

An attempted, incomplete, or unverifiable restoration is a failed outcome, not
a completed rollback. Rollback must never restore or copy the substitute
candidate volume, and it must never use a recursive chown outside the exact
journal.

## Mandatory signed evidence

For a successful `deploy-run` or `candidate-run` that evaluates this profile,
the controller receipt must contain unique bindings for all of these evidence
kinds, even when the ownership journal records zero changes:

- `public-tour-volume-pre-manifest`
- `public-tour-volume-post-manifest`
- `public-tour-volume-ownership-journal`
- `public-tour-volume-mount-proof`

A `failed` or `rolled-back` run after any volume mutation must additionally bind
`public-tour-volume-rollback-proof`. The rollback proof must name which allowed
terminal state was used and bind the final verified manifest and runtime-access
result.

Evidence documents must be written outside candidate authority, canonicalized,
content-addressed, retained with the controller receipt, and independently
verifiable. Missing, duplicated, unreadable, unbound, or internally
inconsistent mandatory evidence fails closed. A generic runtime smoke or
generic rollback assertion is not a substitute for any profile evidence.
