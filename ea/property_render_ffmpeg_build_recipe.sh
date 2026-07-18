#!/usr/bin/env bash
set -euo pipefail

readonly SOURCES_DIR="/sources"
readonly BUILD_DIR="/build"
readonly OUT_DIR="/out/propertyquarry"
readonly EXPECTED_APK_MANIFEST="/usr/local/share/propertyquarry/expected-ffmpeg-builder-apk-manifest.txt"
readonly FFMPEG_SHA256="464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"
readonly FFMPEG_SIGNATURE_SHA256="0a0963fccd70597838073f3e31b20f4a4d8cc2b5e577472c9a5a1f22624246f8"
readonly FFMPEG_KEY_SHA256="397b3becedcd5a98769967ff1ff8501ddc89f8368b8f766e4701377d7dbaabe5"
readonly FFMPEG_SIGNING_FINGERPRINT="FCF986EA15E6E293A5644F10B4322F04D67658D8"
readonly X264_SHA256="d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50"
readonly OUTPUT_SHA256="742e5e1808ca6f3e0109567babd422c10adcde207a75ab446279aa7121fb2272"
readonly OUTPUT_SIZE="3046504"

export LC_ALL=C
export TZ=UTC

mkdir -p "${BUILD_DIR}/x264" "${BUILD_DIR}/ffmpeg" "${OUT_DIR}/licenses"

apk info -v | sort > "${OUT_DIR}/ffmpeg-builder-apk-manifest.txt"
cmp "${EXPECTED_APK_MANIFEST}" "${OUT_DIR}/ffmpeg-builder-apk-manifest.txt"

(
    cd "${SOURCES_DIR}"
    sha256sum -c - <<EOF
${FFMPEG_SHA256}  ffmpeg-8.1.2.tar.xz
${FFMPEG_SIGNATURE_SHA256}  ffmpeg-8.1.2.tar.xz.asc
${FFMPEG_KEY_SHA256}  ffmpeg-devel.asc
${X264_SHA256}  x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee.tar.gz
EOF
)

export GNUPGHOME
GNUPGHOME="$(mktemp -d)"
cleanup_gnupg() {
    gpgconf --kill all >/dev/null 2>&1 || true
    rm -rf "${GNUPGHOME}"
}
trap cleanup_gnupg EXIT
actual_fingerprint="$(
    gpg --batch --with-colons --show-keys --fingerprint "${SOURCES_DIR}/ffmpeg-devel.asc" \
        | awk -F: '$1 == "fpr" { print $10; exit }'
)"
test "${actual_fingerprint}" = "${FFMPEG_SIGNING_FINGERPRINT}"
gpg --batch --import "${SOURCES_DIR}/ffmpeg-devel.asc"
gpg --batch --verify \
    "${SOURCES_DIR}/ffmpeg-8.1.2.tar.xz.asc" \
    "${SOURCES_DIR}/ffmpeg-8.1.2.tar.xz"

tar --extract \
    --file "${SOURCES_DIR}/x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee.tar.gz" \
    --directory "${BUILD_DIR}/x264" \
    --strip-components 1
(
    cd "${BUILD_DIR}/x264"
    ./configure \
        --prefix=/opt/codec \
        --enable-static \
        --disable-cli \
        --disable-opencl \
        --disable-lavf \
        --disable-swscale \
        --disable-interlaced \
        --bit-depth=8 \
        --chroma-format=420
    make -j4
    make install-lib-static
)

tar --extract \
    --file "${SOURCES_DIR}/ffmpeg-8.1.2.tar.xz" \
    --directory "${BUILD_DIR}/ffmpeg" \
    --strip-components 1
(
    cd "${BUILD_DIR}/ffmpeg"
    PKG_CONFIG_PATH=/opt/codec/lib/pkgconfig ./configure \
        --prefix=/opt/ffmpeg \
        --pkg-config-flags=--static \
        --extra-cflags=-I/opt/codec/include \
        --extra-ldflags='-L/opt/codec/lib -static' \
        --extra-libs='-lpthread -lm' \
        --enable-static \
        --disable-shared \
        --disable-everything \
        --disable-autodetect \
        --disable-network \
        --disable-doc \
        --disable-debug \
        --disable-avdevice \
        --disable-swresample \
        --disable-iconv \
        --disable-ffprobe \
        --disable-ffplay \
        --enable-ffmpeg \
        --enable-small \
        --enable-gpl \
        --enable-libx264 \
        --enable-protocol=file \
        --enable-protocol=pipe \
        --enable-demuxer=rawvideo \
        --enable-decoder=rawvideo \
        --enable-encoder=libx264 \
        --enable-muxer=mov \
        --enable-muxer=mp4 \
        --enable-filter=fps \
        --enable-filter=format \
        --enable-filter=scale
    make -j4
    make install
)

strip /opt/ffmpeg/bin/ffmpeg
install -m 0555 /opt/ffmpeg/bin/ffmpeg "${OUT_DIR}/ffmpeg"
test "$(stat -c %s "${OUT_DIR}/ffmpeg")" = "${OUTPUT_SIZE}"
printf '%s  %s\n' "${OUTPUT_SHA256}" ffmpeg | (
    cd "${OUT_DIR}"
    sha256sum -c -
)
test -z "$(scanelf -q -n "${OUT_DIR}/ffmpeg")"
test ! -e /opt/ffmpeg/bin/ffprobe
test ! -e /opt/ffmpeg/bin/ffplay

"${OUT_DIR}/ffmpeg" -buildconf > "${OUT_DIR}/ffmpeg-buildconf.txt" 2>&1
cp "${BUILD_DIR}/ffmpeg/COPYING.GPLv2" "${OUT_DIR}/licenses/ffmpeg-COPYING.GPLv2"
cp "${BUILD_DIR}/x264/COPYING" "${OUT_DIR}/licenses/x264-COPYING"

dd if=/dev/zero bs=12 count=1 2>/dev/null \
    | "${OUT_DIR}/ffmpeg" \
        -hide_banner -loglevel error \
        -f rawvideo -pixel_format rgb24 -video_size 2x2 -framerate 1 -i pipe:0 \
        -map 0:v:0 -vf 'fps=1,format=yuv420p' -frames:v 1 -an -sn -dn \
        -c:v libx264 -pix_fmt yuv420p -movflags +faststart -f mp4 -y /tmp/smoke.mp4
test -s /tmp/smoke.mp4
rm -f /tmp/smoke.mp4
