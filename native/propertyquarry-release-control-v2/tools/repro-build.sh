#!/bin/sh
set -eu
PATH=/usr/bin:/bin
LANG=C
LC_ALL=C
TZ=UTC
export PATH LANG LC_ALL TZ

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SOURCE_ROOT/../.." && pwd)
DEFAULT_FINAL="$REPOSITORY_ROOT/build/propertyquarry-release-control-v2/linux-amd64"
FINAL_ROOT=${1:-"$DEFAULT_FINAL"}
GO_ARCHIVE=${PROPERTYQUARRY_GO_ARCHIVE:-}
EXPECTED_ARCHIVE_SHA=5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053
EXPECTED_ARCHIVE_BYTES=66879095
EXPECTED_GO_SHA=8da5fd321795754b994c64e3eb8a5a14ff47bd285559a7e876f3c79abafc67f9
SCRATCH_EXECUTION_CONTRACT=linux-amd64-static-et-exec-v1
WORK_ROOT=$(mktemp -d /tmp/propertyquarry-release-control-v2-repro.XXXXXX)
trap 'rm -rf -- "$WORK_ROOT"' EXIT HUP INT TERM

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
  [ -f "$manifest_path" ] && [ ! -L "$manifest_path" ] || fail "copied source manifest is invalid"
  [ "$(realpath -e -- "$manifest_path")" = "$manifest_path" ] ||
    fail "copied source manifest contains a symlink"
  : >"$hash_list"
  entry_count=0
  while IFS= read -r relative || [ -n "$relative" ]; do
    case "$relative" in
      ""|/*|*..*) fail "source manifest path is invalid" ;;
    esac
    source_path="$manifest_root/$relative"
    [ -f "$source_path" ] && [ ! -L "$source_path" ] || fail "copied source entry is invalid"
    [ "$(realpath -e -- "$source_path")" = "$source_path" ] ||
      fail "copied source entry contains a symlink"
    file_sha=$(digest "$source_path") || fail "copied source entry cannot be hashed"
    printf '%s  %s\n' "$file_sha" "$relative" >>"$hash_list"
    entry_count=$((entry_count + 1))
  done <"$manifest_path"
  [ "$entry_count" -gt 0 ] || fail "copied source manifest is empty"
  digest "$hash_list" || fail "copied source manifest cannot be hashed"
)

[ "$#" -le 1 ] || fail "usage: repro-build.sh [final-root]"
[ -n "$GO_ARCHIVE" ] || fail "PROPERTYQUARRY_GO_ARCHIVE is required"
[ -f "$GO_ARCHIVE" ] && [ ! -L "$GO_ARCHIVE" ] ||
  fail "toolchain archive must be a regular non-symlink file"
[ "$(stat -c '%s' -- "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_BYTES" ] ||
  fail "toolchain archive size mismatch"
[ "$(digest "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_SHA" ] || fail "toolchain archive digest mismatch"

CANONICAL_FINAL=$(realpath -m -- "$FINAL_ROOT")
CANONICAL_DEFAULT=$(realpath -m -- "$DEFAULT_FINAL")
[ "$CANONICAL_DEFAULT" = "$DEFAULT_FINAL" ] || fail "repository build path contains a symlink"
case "$CANONICAL_FINAL" in
  "$CANONICAL_DEFAULT"|/tmp/*) ;;
  *) fail "final output must be the repository build path or an isolated /tmp path" ;;
esac
[ ! -L "$FINAL_ROOT" ] || fail "final output must not be a symlink"
mkdir -p "$FINAL_ROOT"
[ "$(realpath -e -- "$FINAL_ROOT")" = "$CANONICAL_FINAL" ] || fail "final output path changed"

EXPECTED_FINAL_FILES=$(printf '%s\n' \
  build-receipt.json \
  propertyquarry-release-controller-v2 \
  propertyquarry-release-supervisor-v2 \
  propertyquarry-release-watchdog-v2)
CURRENT_FINAL_FILES=$(find "$FINAL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n') ||
  fail "final output cannot be enumerated"
if [ -n "$CURRENT_FINAL_FILES" ]; then
  CURRENT_FINAL_FILES=$(printf '%s\n' "$CURRENT_FINAL_FILES" | LC_ALL=C sort)
  [ "$CURRENT_FINAL_FILES" = "$EXPECTED_FINAL_FILES" ] ||
    fail "final bundle contains an unexpected entry"
fi
for entry in $EXPECTED_FINAL_FILES; do
  target="$FINAL_ROOT/$entry"
  [ ! -L "$target" ] || fail "final bundle target must not be a symlink"
  [ ! -e "$target" ] || [ -f "$target" ] || fail "final bundle target type is invalid"
done

SOURCE_MANIFEST="$SOURCE_ROOT/tools/source-files.txt"
[ -f "$SOURCE_MANIFEST" ] && [ ! -L "$SOURCE_MANIFEST" ] || fail "source manifest is invalid"
[ "$(realpath -e -- "$SOURCE_MANIFEST")" = "$SOURCE_MANIFEST" ] ||
  fail "source manifest contains a symlink"
MANIFEST_SNAPSHOT="$WORK_ROOT/source-files.txt"
install -m 0644 "$SOURCE_MANIFEST" "$MANIFEST_SNAPSHOT"

copy_source() {
  destination=$1
  mkdir -p "$destination"
  entry_count=0
  while IFS= read -r relative || [ -n "$relative" ]; do
    case "$relative" in
      ""|/*|*..*) fail "source manifest path is invalid" ;;
    esac
    source_path="$SOURCE_ROOT/$relative"
    if [ "$relative" = tools/source-files.txt ]; then
      source_path=$MANIFEST_SNAPSHOT
    else
      [ -f "$source_path" ] && [ ! -L "$source_path" ] || fail "source manifest entry is invalid"
      [ "$(realpath -e -- "$source_path")" = "$source_path" ] ||
        fail "source manifest entry contains a symlink"
    fi
    mode=0644
    case "$relative" in tools/*.sh) mode=0755 ;; esac
    install -D -m "$mode" "$source_path" "$destination/$relative"
    entry_count=$((entry_count + 1))
  done <"$MANIFEST_SNAPSHOT"
  [ "$entry_count" -gt 0 ] || fail "source manifest is empty"
}

FIRST_SOURCE="$WORK_ROOT/source-a"
SECOND_SOURCE="$WORK_ROOT/different-absolute-source-b"
FIRST_OUTPUT="$WORK_ROOT/output-a"
SECOND_OUTPUT="$WORK_ROOT/output-b"
copy_source "$FIRST_SOURCE"
copy_source "$SECOND_SOURCE"
FIRST_SOURCE_SHA=$(manifest_digest "$FIRST_SOURCE" "$WORK_ROOT/source-a-hashes-before") ||
  fail "first source copy cannot be authenticated"
SECOND_SOURCE_SHA=$(manifest_digest "$SECOND_SOURCE" "$WORK_ROOT/source-b-hashes-before") ||
  fail "second source copy cannot be authenticated"
[ "$FIRST_SOURCE_SHA" = "$SECOND_SOURCE_SHA" ] || fail "source copies differ"

PROPERTYQUARRY_GO_ARCHIVE="$GO_ARCHIVE" \
PROPERTYQUARRY_BUILD_CACHE_ROOT="$WORK_ROOT/cache-a" \
  "$FIRST_SOURCE/tools/build.sh" "$FIRST_OUTPUT"
PROPERTYQUARRY_GO_ARCHIVE="$GO_ARCHIVE" \
PROPERTYQUARRY_BUILD_CACHE_ROOT="$WORK_ROOT/cache-b" \
  "$SECOND_SOURCE/tools/build.sh" "$SECOND_OUTPUT"

for component in supervisor controller watchdog; do
  name="propertyquarry-release-${component}-v2"
  "$FIRST_SOURCE/tools/verify-static-elf.sh" "$FIRST_OUTPUT/$name" >/dev/null ||
    fail "first binary is not scratch-executable static ELF"
  "$SECOND_SOURCE/tools/verify-static-elf.sh" "$SECOND_OUTPUT/$name" >/dev/null ||
    fail "second binary is not scratch-executable static ELF"
  cmp "$FIRST_OUTPUT/$name" "$SECOND_OUTPUT/$name"
done

[ "$(manifest_digest "$FIRST_SOURCE" "$WORK_ROOT/source-a-hashes-after")" = "$FIRST_SOURCE_SHA" ] ||
  fail "first source copy changed during build"
[ "$(manifest_digest "$SECOND_SOURCE" "$WORK_ROOT/source-b-hashes-after")" = "$SECOND_SOURCE_SHA" ] ||
  fail "second source copy changed during build"
[ "$(stat -c '%s' -- "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_BYTES" ] ||
  fail "toolchain archive changed during build"
[ "$(digest "$GO_ARCHIVE")" = "$EXPECTED_ARCHIVE_SHA" ] ||
  fail "toolchain archive changed during build"

if ! env -i PATH=/usr/bin:/bin PYTHONNOUSERSITE=1 python3 -I -S - \
  "$FIRST_OUTPUT" "sha256:$FIRST_SOURCE_SHA" <<'PY'
import json
from pathlib import Path
import subprocess
import sys


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


try:
    root = Path(sys.argv[1])
    source_digest = sys.argv[2]
    for component in ("controller", "supervisor", "watchdog"):
        name = f"propertyquarry-release-{component}-v2"
        result = subprocess.run(
            [str(root / name), "--build-info-json"],
            check=True,
            capture_output=True,
            env={},
            timeout=5,
        )
        info = json.loads(result.stdout, object_pairs_hook=unique_object)
        if result.stderr != b"" or info != {
            "schema": "propertyquarry.release-control.native-build-info.v2",
            "version": 2,
            "component": name,
            "toolchain": "go1.26.5",
            "source_manifest_digest": source_digest,
            "scratch_execution_contract": "linux-amd64-static-et-exec-v1",
            "authoritative": False,
            "production_ready": False,
            "performs_release_effects": False,
            "self_test": False,
        }:
            raise ValueError("build info mismatch")
except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
then
  fail "built binaries do not authenticate their source manifest"
fi

PUBLISH_ROOT="$WORK_ROOT/publish"
mkdir -m 0700 "$PUBLISH_ROOT"
for component in supervisor controller watchdog; do
  name="propertyquarry-release-${component}-v2"
  install -m 0755 "$FIRST_OUTPUT/$name" "$PUBLISH_ROOT/$name"
  "$FIRST_SOURCE/tools/verify-static-elf.sh" "$PUBLISH_ROOT/$name" >/dev/null ||
    fail "publish binary is not scratch-executable static ELF"
done

SUPERVISOR_SHA=$(digest "$PUBLISH_ROOT/propertyquarry-release-supervisor-v2")
CONTROLLER_SHA=$(digest "$PUBLISH_ROOT/propertyquarry-release-controller-v2")
WATCHDOG_SHA=$(digest "$PUBLISH_ROOT/propertyquarry-release-watchdog-v2")
SUPERVISOR_BYTES=$(stat -c '%s' -- "$PUBLISH_ROOT/propertyquarry-release-supervisor-v2")
CONTROLLER_BYTES=$(stat -c '%s' -- "$PUBLISH_ROOT/propertyquarry-release-controller-v2")
WATCHDOG_BYTES=$(stat -c '%s' -- "$PUBLISH_ROOT/propertyquarry-release-watchdog-v2")
LDFLAGS="-buildid= -linkmode=internal -X propertyquarry.local/release-control-v2/internal/releasecontrol.SourceManifestDigest=sha256:$FIRST_SOURCE_SHA -X propertyquarry.local/release-control-v2/internal/releasecontrol.ScratchExecutionContract=$SCRATCH_EXECUTION_CONTRACT"

printf '%s\n' \
  '{' \
  '  "schema": "propertyquarry.release-control.native-build-receipt.v2",' \
  '  "authoritative": false,' \
  '  "production_ready": false,' \
  '  "reproducible_double_build": true,' \
  '  "distinct_absolute_source_roots": true,' \
  '  "isolated_build_caches": true,' \
  '  "independent_toolchain_extractions": true,' \
  '  "go_subprocess_environment_allowlisted": true,' \
  '  "go_subprocess_inherited_environment_cleared": true,' \
  '  "module_network_resolution_disabled": true,' \
  '  "host_network_namespace_isolated": false,' \
  '  "go_tests_passed_in_both_builds": true,' \
  '  "scratch_execution": {' \
  "    \"contract\": \"$SCRATCH_EXECUTION_CONTRACT\"," \
  '    "elf_class": "ELF64",' \
  '    "elf_data": "little-endian",' \
  '    "elf_machine": "Advanced Micro Devices X86-64",' \
  '    "elf_type": "ET_EXEC",' \
  '    "statically_linked": true,' \
  '    "pt_interp_absent": true,' \
  '    "dynamic_section_absent": true,' \
  '    "dt_needed_absent": true,' \
  '    "non_executable_stack": true,' \
  '    "writable_executable_load_segments_absent": true,' \
  '    "file_gate_passed": true,' \
  '    "readelf_gate_passed": true' \
  '  },' \
  '  "source_manifest_reverified_after_build": true,' \
  '  "receipt_published_last": true,' \
  '  "root_install_performed": false,' \
  '  "package_signature_verified": false,' \
  '  "builder_identity_authenticated": false,' \
  '  "toolchain": "go1.26.5 linux/amd64",' \
  '  "toolchain_archive_bytes": 66879095,' \
  '  "toolchain_archive_sha256": "5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053",' \
  "  \"go_binary_sha256\": \"sha256:$EXPECTED_GO_SHA\"," \
  "  \"source_manifest_sha256\": \"sha256:$FIRST_SOURCE_SHA\"," \
  '  "build_flags": ["-mod=readonly", "-trimpath", "-buildvcs=false", "-buildmode=exe"],' \
  "  \"ldflags\": \"$LDFLAGS\"," \
  '  "build_environment": {' \
  '    "CGO_ENABLED": "0",' \
  '    "GO111MODULE": "on",' \
  '    "GOARCH": "amd64",' \
  '    "GOAMD64": "v1",' \
  '    "GOENV": "off",' \
  '    "GOEXPERIMENT": "",' \
  '    "GOFIPS140": "off",' \
  '    "GOFLAGS": "",' \
  '    "GOOS": "linux",' \
  '    "GOPROXY": "off",' \
  '    "GOSUMDB": "off",' \
  '    "GOTELEMETRY": "off",' \
  '    "GOTOOLCHAIN": "local",' \
  '    "GOWORK": "off",' \
  '    "LANG": "C",' \
  '    "LC_ALL": "C",' \
  '    "TZ": "UTC"' \
  '  },' \
  '  "binary_mode": "0755",' \
  '  "binary_sizes": {' \
  "    \"propertyquarry-release-controller-v2\": $CONTROLLER_BYTES," \
  "    \"propertyquarry-release-supervisor-v2\": $SUPERVISOR_BYTES," \
  "    \"propertyquarry-release-watchdog-v2\": $WATCHDOG_BYTES" \
  '  },' \
  '  "binaries": {' \
  "    \"propertyquarry-release-controller-v2\": \"sha256:$CONTROLLER_SHA\"," \
  "    \"propertyquarry-release-supervisor-v2\": \"sha256:$SUPERVISOR_SHA\"," \
  "    \"propertyquarry-release-watchdog-v2\": \"sha256:$WATCHDOG_SHA\"" \
  '  }' \
  '}' >"$PUBLISH_ROOT/build-receipt.json"
chmod 0644 "$PUBLISH_ROOT/build-receipt.json"

PUBLISH_FILES=$(find "$PUBLISH_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n') ||
  fail "publish bundle cannot be enumerated"
PUBLISH_FILES=$(printf '%s\n' "$PUBLISH_FILES" | LC_ALL=C sort)
[ "$PUBLISH_FILES" = "$EXPECTED_FINAL_FILES" ] || fail "publish bundle contains an unexpected entry"
[ -z "$(find "$PUBLISH_ROOT" -mindepth 1 -maxdepth 1 -type l -print -quit)" ] ||
  fail "publish bundle contains a symlink"

for component in supervisor controller watchdog; do
  name="propertyquarry-release-${component}-v2"
  install -m 0755 "$PUBLISH_ROOT/$name" "$FINAL_ROOT/$name"
done
install -m 0644 "$PUBLISH_ROOT/build-receipt.json" "$FINAL_ROOT/build-receipt.json"

FINAL_FILES=$(find "$FINAL_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n') ||
  fail "final bundle cannot be enumerated"
FINAL_FILES=$(printf '%s\n' "$FINAL_FILES" | LC_ALL=C sort)
[ "$FINAL_FILES" = "$EXPECTED_FINAL_FILES" ] || fail "final bundle contains an unexpected entry"
[ -z "$(find "$FINAL_ROOT" -mindepth 1 -maxdepth 1 -type l -print -quit)" ] ||
  fail "final bundle contains a symlink"
cmp "$PUBLISH_ROOT/build-receipt.json" "$FINAL_ROOT/build-receipt.json"
for component in supervisor controller watchdog; do
  name="propertyquarry-release-${component}-v2"
  cmp "$PUBLISH_ROOT/$name" "$FINAL_ROOT/$name"
  [ "$(stat -c '%a' -- "$FINAL_ROOT/$name")" = 755 ] || fail "binary mode is invalid"
  "$FIRST_SOURCE/tools/verify-static-elf.sh" "$FINAL_ROOT/$name" >/dev/null ||
    fail "final binary is not scratch-executable static ELF"
done
[ "$(stat -c '%a' -- "$FINAL_ROOT/build-receipt.json")" = 644 ] || fail "build receipt mode is invalid"

printf '%s\n' "$FINAL_ROOT/build-receipt.json"
