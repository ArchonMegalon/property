#!/bin/sh
set -eu
PATH=/usr/bin:/bin
LANG=C
LC_ALL=C
TZ=UTC
export PATH LANG LC_ALL TZ

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SOURCE_ROOT/../.." && pwd)
DEFAULT_OUTPUT="$REPOSITORY_ROOT/build/propertyquarry-release-control-v2/linux-amd64"
OUTPUT_ROOT=${1:-"$DEFAULT_OUTPUT"}
GO_ARCHIVE=${PROPERTYQUARRY_GO_ARCHIVE:-}
EXPECTED_ARCHIVE_SHA=5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053
EXPECTED_ARCHIVE_BYTES=66879095
EXPECTED_GO_SHA=8da5fd321795754b994c64e3eb8a5a14ff47bd285559a7e876f3c79abafc67f9

fail() {
  printf '%s\n' "error: $1" >&2
  exit 1
}

digest() {
  digest_output=$(sha256sum -- "$1") || return 1
  printf '%s\n' "${digest_output%% *}"
}

manifest_digest() (
  manifest_root=$1
  hash_list=$2
  manifest_path="$manifest_root/tools/source-files.txt"
  [ -f "$manifest_path" ] && [ ! -L "$manifest_path" ] || fail "source manifest is invalid"
  [ "$(realpath -e -- "$manifest_path")" = "$manifest_path" ] ||
    fail "source manifest contains a symlink"
  : >"$hash_list"
  entry_count=0
  while IFS= read -r relative || [ -n "$relative" ]; do
    case "$relative" in
      ""|/*|*..*) fail "source manifest path is invalid" ;;
    esac
    source_path="$manifest_root/$relative"
    [ -f "$source_path" ] && [ ! -L "$source_path" ] || fail "source manifest entry is invalid"
    [ "$(realpath -e -- "$source_path")" = "$source_path" ] ||
      fail "source manifest entry contains a symlink"
    file_sha=$(digest "$source_path") || fail "source manifest entry cannot be hashed"
    printf '%s  %s\n' "$file_sha" "$relative" >>"$hash_list"
    entry_count=$((entry_count + 1))
  done <"$manifest_path"
  [ "$entry_count" -gt 0 ] || fail "source manifest is empty"
  digest "$hash_list" || fail "source manifest cannot be hashed"
)

[ "$#" -le 1 ] || fail "usage: build.sh [output-root]"
PRIVATE_ROOT=$(mktemp -d /tmp/propertyquarry-release-control-v2-build.XXXXXX)
trap 'rm -rf -- "$PRIVATE_ROOT"' EXIT HUP INT TERM

[ -n "$GO_ARCHIVE" ] || fail "PROPERTYQUARRY_GO_ARCHIVE is required"
[ -f "$GO_ARCHIVE" ] && [ ! -L "$GO_ARCHIVE" ] ||
  fail "toolchain archive must be a regular non-symlink file"
[ "$(stat -c '%s' -- "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_BYTES" ] ||
  fail "toolchain archive size mismatch"
[ "$(digest "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_SHA" ] ||
  fail "toolchain archive digest mismatch"

TOOLCHAIN_ROOT="$PRIVATE_ROOT/toolchain"
mkdir -m 0700 "$TOOLCHAIN_ROOT"
env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C TZ=UTC tar --extract \
  --gzip \
  --file "$GO_ARCHIVE" \
  --directory "$TOOLCHAIN_ROOT" \
  --no-same-owner \
  --no-same-permissions
[ "$(stat -c '%s' -- "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_BYTES" ] ||
  fail "toolchain archive changed during extraction"
[ "$(digest "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_SHA" ] ||
  fail "toolchain archive changed during extraction"
GOROOT="$TOOLCHAIN_ROOT/go"
GO_BINARY="$GOROOT/bin/go"
[ -d "$GOROOT" ] && [ ! -L "$GOROOT" ] || fail "extracted GOROOT is invalid"
[ -f "$GO_BINARY" ] && [ ! -L "$GO_BINARY" ] && [ -x "$GO_BINARY" ] ||
  fail "extracted Go binary is invalid"
[ "$(realpath -e -- "$GO_BINARY")" = "$GO_BINARY" ] || fail "extracted Go binary contains a symlink"
[ "$(digest "$GO_BINARY")" = "$EXPECTED_GO_SHA" ] || fail "extracted Go binary digest mismatch"
[ "$(env -i PATH=/usr/bin:/bin GOROOT="$GOROOT" GOTOOLCHAIN=local "$GO_BINARY" version)" = "go version go1.26.5 linux/amd64" ] ||
  fail "exact Go 1.26.5 linux/amd64 toolchain required"

CANONICAL_OUTPUT=$(realpath -m -- "$OUTPUT_ROOT")
CANONICAL_REPOSITORY_OUTPUT=$(realpath -m -- "$DEFAULT_OUTPUT")
[ "$CANONICAL_REPOSITORY_OUTPUT" = "$DEFAULT_OUTPUT" ] ||
  fail "repository build path contains a symlink"
case "$CANONICAL_OUTPUT" in
  "$CANONICAL_REPOSITORY_OUTPUT"|/tmp/*) ;;
  *) fail "output must be the repository build path or an isolated /tmp path" ;;
esac
[ ! -L "$OUTPUT_ROOT" ] || fail "output directory must not be a symlink"
mkdir -p "$OUTPUT_ROOT"
[ "$(realpath -e -- "$OUTPUT_ROOT")" = "$CANONICAL_OUTPUT" ] ||
  fail "output path changed during creation"
[ ! -e "$OUTPUT_ROOT/build-receipt.json" ] && [ ! -L "$OUTPUT_ROOT/build-receipt.json" ] ||
  fail "refusing to overwrite a receipted bundle; use repro-build.sh"

SOURCE_MANIFEST_SHA=$(manifest_digest "$SOURCE_ROOT" "$PRIVATE_ROOT/source-hashes-before") ||
  fail "source manifest cannot be authenticated"

if [ -n "${PROPERTYQUARRY_BUILD_CACHE_ROOT:-}" ]; then
  CACHE_ROOT=$PROPERTYQUARRY_BUILD_CACHE_ROOT
else
  CACHE_ROOT="$PRIVATE_ROOT/cache"
fi
CANONICAL_CACHE=$(realpath -m -- "$CACHE_ROOT")
case "$CANONICAL_CACHE" in
  /tmp/*) ;;
  *) fail "build cache must be isolated under /tmp" ;;
esac
[ ! -e "$CACHE_ROOT" ] && [ ! -L "$CACHE_ROOT" ] ||
  fail "build cache must be a new non-symlink path"
mkdir -p \
  "$CACHE_ROOT/gocache" \
  "$CACHE_ROOT/gomodcache" \
  "$CACHE_ROOT/gopath" \
  "$CACHE_ROOT/home" \
  "$CACHE_ROOT/tmp" \
  "$CACHE_ROOT/xdg-cache" \
  "$CACHE_ROOT/xdg-config"
[ "$(realpath -e -- "$CACHE_ROOT")" = "$CANONICAL_CACHE" ] || fail "build cache path changed"

run_go() {
  env -i \
    PATH=/usr/bin:/bin \
    HOME="$CACHE_ROOT/home" \
    LANG=C \
    LC_ALL=C \
    TMPDIR="$CACHE_ROOT/tmp" \
    TZ=UTC \
    XDG_CACHE_HOME="$CACHE_ROOT/xdg-cache" \
    XDG_CONFIG_HOME="$CACHE_ROOT/xdg-config" \
    CGO_ENABLED=0 \
    GO111MODULE=on \
    GOARCH=amd64 \
    GOAMD64=v1 \
    GOCACHE="$CACHE_ROOT/gocache" \
    GOENV=off \
    GOEXPERIMENT= \
    GOFIPS140=off \
    GOFLAGS= \
    GOMODCACHE="$CACHE_ROOT/gomodcache" \
    GOOS=linux \
    GOPATH="$CACHE_ROOT/gopath" \
    GOPROXY=off \
    GOROOT="$GOROOT" \
    GOSUMDB=off \
    GOTELEMETRY=off \
    GOTOOLCHAIN=local \
    GOTMPDIR="$CACHE_ROOT/tmp" \
    GOWORK=off \
    "$GO_BINARY" "$@"
}

run_go test -C "$SOURCE_ROOT" -mod=readonly ./... >&2

SCRATCH_EXECUTION_CONTRACT=linux-amd64-static-et-exec-v1
LDFLAGS="-buildid= -linkmode=internal -X propertyquarry.local/release-control-v2/internal/releasecontrol.SourceManifestDigest=sha256:$SOURCE_MANIFEST_SHA -X propertyquarry.local/release-control-v2/internal/releasecontrol.ScratchExecutionContract=$SCRATCH_EXECUTION_CONTRACT"
for component in supervisor controller watchdog; do
  name="propertyquarry-release-${component}-v2"
  target="$OUTPUT_ROOT/$name"
  [ ! -L "$target" ] || fail "binary target must not be a symlink"
  [ ! -e "$target" ] || [ -f "$target" ] || fail "binary target type is invalid"
  run_go build \
    -C "$SOURCE_ROOT" \
    -mod=readonly \
    -trimpath \
    -buildvcs=false \
    -buildmode=exe \
    -ldflags "$LDFLAGS" \
    -o "$target" \
    "./cmd/$name"
  [ -f "$target" ] && [ ! -L "$target" ] || fail "binary output is invalid"
  chmod 0755 "$target"
  "$SOURCE_ROOT/tools/verify-static-elf.sh" "$target" >/dev/null ||
    fail "binary is not scratch-executable static ELF"
done

SOURCE_MANIFEST_SHA_AFTER=$(manifest_digest "$SOURCE_ROOT" "$PRIVATE_ROOT/source-hashes-after") ||
  fail "source manifest cannot be re-authenticated"
[ "$SOURCE_MANIFEST_SHA_AFTER" = "$SOURCE_MANIFEST_SHA" ] || fail "source changed during the build"
[ "$(digest "$GO_BINARY")" = "$EXPECTED_GO_SHA" ] || fail "Go binary changed during the build"
