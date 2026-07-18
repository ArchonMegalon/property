#!/usr/bin/env bash
set -euo pipefail

readonly SOURCES_DIR="/sources"
readonly BUILD_ROOT="/build"
readonly SOURCE_DIR="${BUILD_ROOT}/glib"
readonly OUT_DIR="/out/propertyquarry"
readonly SOURCE_VERSION="2.84.4-3~deb13u3"
readonly RUNTIME_VERSION="2.84.4-3~deb13u3+pq1"
readonly DSC_SHA256="4b9e829d82cb5884e6de4250b4c31fd9030ca1be0c29f9b84e9141ee6d9344c1"
readonly ORIG_SHA256="8a9ea10943c36fc117e253f80c91e477b673525ae45762942858aef57631bb90"
readonly UNICODE_SHA256="c1742461e8c0e9673a3453a3127671169de9cb0138493e5c916f1b989530efcd"
readonly DEBIAN_TAR_SHA256="8e35b56abfed5cea96a93d032996efd3a3a5f445a2fc75445f5f42b4d84f42ef"
readonly RUNTIME_DEB_SHA256="7f78780302454832988b84f1c3c4de31bbbf42a8e3be5dfe69f7980b98384cf8"
readonly FIXED_CHANGELOG_DATE="Sat, 18 Jul 2026 17:24:20 +0000"

export LC_ALL=C.UTF-8
export TZ=UTC
export SOURCE_DATE_EPOCH=1784395460
export DEB_BUILD_OPTIONS="nocheck parallel=8"
export DEB_BUILD_PROFILES="noinsttest nogir nodoc noudeb pkg.glib2.0.nosysprof"

apt-get update
apt-get install --yes --no-install-recommends \
    build-essential \
    ca-certificates \
    debian-keyring \
    devscripts \
    dpkg-dev \
    equivs \
    fakeroot

(
    cd "${SOURCES_DIR}"
    sha256sum -c - <<EOF
${DSC_SHA256}  glib2.0_${SOURCE_VERSION}.dsc
${ORIG_SHA256}  glib2.0_2.84.4.orig.tar.xz
${UNICODE_SHA256}  glib2.0_2.84.4.orig-unicode-data.tar.xz
${DEBIAN_TAR_SHA256}  glib2.0_${SOURCE_VERSION}.debian.tar.xz
EOF
    dscverify "glib2.0_${SOURCE_VERSION}.dsc"
)

mkdir -p "${BUILD_ROOT}" "${OUT_DIR}"
dpkg-source -x "${SOURCES_DIR}/glib2.0_${SOURCE_VERSION}.dsc" "${SOURCE_DIR}"

python3 - "${SOURCE_DIR}" "${RUNTIME_VERSION}" "${FIXED_CHANGELOG_DATE}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
version = sys.argv[2]
fixed_date = sys.argv[3]
rules = source / "debian" / "rules"
text = rules.read_text(encoding="utf-8")
old = "enable_libmount := enabled"
if text.count(old) != 1:
    raise SystemExit("unexpected libmount control count")
rules.write_text(text.replace(old, "enable_libmount := disabled"), encoding="utf-8")

changelog = source / "debian" / "changelog"
existing = changelog.read_text(encoding="utf-8")
entry = (
    f"glib2.0 ({version}) trixie; urgency=medium\n\n"
    "  * Disable libmount in the PropertyQuarry runtime rebuild.\n\n"
    f" -- PropertyQuarry Build <build@propertyquarry.invalid>  {fixed_date}\n\n"
)
changelog.write_text(entry + existing, encoding="utf-8")
PY

(
    cd "${SOURCE_DIR}"
    mk-build-deps \
        --install \
        --remove \
        --tool 'apt-get --yes --no-install-recommends' \
        debian/control
    dpkg-buildpackage -us -uc -B
)

readonly BUILT_DEB="${BUILD_ROOT}/libglib2.0-0t64_${RUNTIME_VERSION}_amd64.deb"
test -f "${BUILT_DEB}"
printf '%s  %s\n' "${RUNTIME_DEB_SHA256}" "$(basename "${BUILT_DEB}")" | (
    cd "${BUILD_ROOT}"
    sha256sum -c -
)
test "$(dpkg-deb -f "${BUILT_DEB}" Package)" = "libglib2.0-0t64"
test "$(dpkg-deb -f "${BUILT_DEB}" Version)" = "${RUNTIME_VERSION}"
dpkg-deb -f "${BUILT_DEB}" Depends \
    | python3 -c 'import sys; raise SystemExit("libmount" in sys.stdin.read())'

install -m 0444 "${BUILT_DEB}" "${OUT_DIR}/$(basename "${BUILT_DEB}")"
install -m 0444 \
    "${BUILD_ROOT}/glib2.0_${RUNTIME_VERSION}_amd64.buildinfo" \
    "${OUT_DIR}/glib-buildinfo"
dpkg-query -W -f='${db:Status-Status}\t${binary:Package}\t${Version}\n' \
    | sort > "${OUT_DIR}/glib-builder-dpkg-manifest.txt"
