"""Validate the bounded FFmpeg surface shipped in the render runtime."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

RUNTIME_MEDIA_PROVENANCE_PATH = Path(
    "/usr/local/share/propertyquarry/render-media-provenance.json"
)
RUNTIME_BUILD_RECEIPT_PATHS = {
    "apk_manifest": Path(
        "/usr/local/share/propertyquarry/receipts/ffmpeg-builder-apk-manifest.txt"
    ),
    "ffmpeg_recipe": Path(
        "/usr/local/share/propertyquarry/receipts/ffmpeg-build-receipt.json"
    ),
    "glib_recipe": Path(
        "/usr/local/share/propertyquarry/receipts/glib-build-receipt.json"
    ),
}
FFMPEG_EXPECTED_VERSION = "8.1.2"
FFMPEG_EXPECTED_BINARY_SHA256 = (
    "742e5e1808ca6f3e0109567babd422c10adcde207a75ab446279aa7121fb2272"
)
FFMPEG_EXPECTED_BINARY_SIZE = 3_046_504
FFMPEG_EXPECTED_SOURCE_URL = "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz"
FFMPEG_EXPECTED_SOURCE_SHA256 = (
    "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"
)
FFMPEG_EXPECTED_SIGNATURE_URL = (
    "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz.asc"
)
FFMPEG_EXPECTED_SIGNATURE_SHA256 = (
    "0a0963fccd70597838073f3e31b20f4a4d8cc2b5e577472c9a5a1f22624246f8"
)
FFMPEG_EXPECTED_SIGNING_KEY_URL = "https://ffmpeg.org/ffmpeg-devel.asc"
FFMPEG_EXPECTED_SIGNING_KEY_SHA256 = (
    "397b3becedcd5a98769967ff1ff8501ddc89f8368b8f766e4701377d7dbaabe5"
)
FFMPEG_EXPECTED_SIGNING_FINGERPRINT = "FCF986EA15E6E293A5644F10B4322F04D67658D8"
FFMPEG_EXPECTED_BUILDER_IMAGE = (
    "alpine:3.22@sha256:"
    "14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
)
X264_EXPECTED_COMMIT = "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee"
X264_EXPECTED_ARCHIVE_URL = (
    "https://code.videolan.org/videolan/x264/-/archive/"
    f"{X264_EXPECTED_COMMIT}/x264-{X264_EXPECTED_COMMIT}.tar.gz"
)
X264_EXPECTED_ARCHIVE_SHA256 = (
    "d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50"
)
GLIB_EXPECTED_VERSION = "2.84.4-3~deb13u3+pq1"
GLIB_EXPECTED_BUILDER_IMAGE = (
    "debian:13.6-slim@sha256:"
    "020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd"
)
GLIB_EXPECTED_SNAPSHOT_ROOT = (
    "https://snapshot.debian.org/archive/debian/20260713T000000Z/"
    "pool/main/g/glib2.0/"
)
GLIB_EXPECTED_SOURCE_HASHES = {
    "dsc_sha256": "4b9e829d82cb5884e6de4250b4c31fd9030ca1be0c29f9b84e9141ee6d9344c1",
    "orig_sha256": "8a9ea10943c36fc117e253f80c91e477b673525ae45762942858aef57631bb90",
    "unicode_sha256": "c1742461e8c0e9673a3453a3127671169de9cb0138493e5c916f1b989530efcd",
    "debian_tar_sha256": "8e35b56abfed5cea96a93d032996efd3a3a5f445a2fc75445f5f42b4d84f42ef",
}
GLIB_EXPECTED_RUNTIME_DEB_SHA256 = (
    "7f78780302454832988b84f1c3c4de31bbbf42a8e3be5dfe69f7980b98384cf8"
)
FFMPEG_REQUIRED_FILTERS = frozenset({"format", "fps", "scale"})
FFMPEG_ALLOWED_RUNTIME_FILTERS = frozenset(
    {
        "abuffer",
        "abuffersink",
        "aformat",
        "anull",
        "atrim",
        "buffer",
        "buffersink",
        "crop",
        "format",
        "fps",
        "hflip",
        "null",
        "rotate",
        "scale",
        "transpose",
        "trim",
        "vflip",
    }
)
FFMPEG_REQUIRED_PROTOCOLS = frozenset({"file", "pipe"})
FFMPEG_REQUIRED_ENABLE_FLAGS = frozenset(
    {
        "--enable-decoder=rawvideo",
        "--enable-demuxer=rawvideo",
        "--enable-encoder=libx264",
        "--enable-ffmpeg",
        "--enable-filter=format",
        "--enable-filter=fps",
        "--enable-filter=scale",
        "--enable-gpl",
        "--enable-libx264",
        "--enable-muxer=mov",
        "--enable-muxer=mp4",
        "--enable-protocol=file",
        "--enable-protocol=pipe",
        "--enable-small",
        "--enable-static",
    }
)
FFMPEG_REQUIRED_DISABLE_FLAGS = frozenset(
    {
        "--disable-autodetect",
        "--disable-debug",
        "--disable-doc",
        "--disable-everything",
        "--disable-avdevice",
        "--disable-ffplay",
        "--disable-ffprobe",
        "--disable-iconv",
        "--disable-network",
        "--disable-shared",
        "--disable-swresample",
    }
)
FFMPEG_REQUIRED_OTHER_CONFIGURE_FLAGS = frozenset(
    {
        "--extra-cflags=-I/opt/codec/include",
        "--extra-ldflags=-L/opt/codec/lib -static",
        "--extra-libs=-lpthread -lm",
        "--pkg-config-flags=--static",
        "--prefix=/opt/ffmpeg",
    }
)
FFMPEG_REQUIRED_CONFIGURE_FLAGS = (
    FFMPEG_REQUIRED_ENABLE_FLAGS
    | FFMPEG_REQUIRED_DISABLE_FLAGS
    | FFMPEG_REQUIRED_OTHER_CONFIGURE_FLAGS
)
FFMPEG_ALLOWED_RUNTIME_DECODERS = frozenset({"rawvideo"})
FFMPEG_ALLOWED_RUNTIME_DEMUXERS = frozenset({"rawvideo"})
FFMPEG_ALLOWED_RUNTIME_ENCODERS = frozenset({"libx264"})
FFMPEG_ALLOWED_RUNTIME_MUXERS = frozenset({"mov", "mp4"})
FFMPEG_ALLOWED_RUNTIME_PARSERS = frozenset({"ac3"})
FFMPEG_ALLOWED_RUNTIME_BITSTREAM_FILTERS = frozenset(
    {"aac_adtstoasc", "vp9_superframe"}
)
FFMPEG_ALLOWED_RUNTIME_HWACCELS: frozenset[str] = frozenset()
FFMPEG_EXPECTED_LICENSE = "GPL-2.0-or-later"
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def capture_local_tool(command: str, *args: str) -> dict[str, object]:
    executable = shutil.which(command)
    if not executable:
        return {
            "available": False,
            "path": "",
            "returncode": None,
            "output": "",
        }
    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {
            "available": False,
            "path": executable,
            "returncode": None,
            "output": "",
            "reason": type(exc).__name__,
        }
    output = "\n".join(
        value.strip()
        for value in (completed.stdout or "", completed.stderr or "")
        if value.strip()
    )
    return {
        "available": completed.returncode == 0,
        "path": executable,
        "returncode": int(completed.returncode),
        "output": output,
    }


def capture_container_tool(container: str, command: str, *args: str) -> dict[str, object]:
    docker = shutil.which("docker")
    if not container:
        return {
            "available": False,
            "container": "",
            "path": "",
            "returncode": None,
            "output": "",
        }
    if not docker:
        return {
            "available": False,
            "container": container,
            "path": "",
            "returncode": None,
            "output": "",
            "reason": "docker_missing",
        }
    resolver = (
        "import shutil, sys; "
        "resolved = shutil.which(sys.argv[1]); "
        "print(resolved or '')"
    )
    try:
        resolved = subprocess.run(
            [
                docker,
                "exec",
                container,
                "/usr/local/bin/python",
                "-I",
                "-c",
                resolver,
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        resolved_path = (resolved.stdout or "").strip().splitlines()
        executable = resolved_path[0] if resolved.returncode == 0 and resolved_path else ""
        if not executable:
            return {
                "available": False,
                "container": container,
                "path": "",
                "returncode": None,
                "output": "",
                "reason": "command_missing"
                if resolved.returncode == 0
                else "command_resolution_failed",
            }
        completed = subprocess.run(
            [docker, "exec", container, executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {
            "available": False,
            "container": container,
            "path": "",
            "returncode": None,
            "output": "",
            "reason": type(exc).__name__,
        }
    output = "\n".join(
        value.strip()
        for value in (completed.stdout or "", completed.stderr or "")
        if value.strip()
    )
    return {
        "available": completed.returncode == 0,
        "container": container,
        "path": executable,
        "returncode": int(completed.returncode),
        "output": output,
    }


def _ffmpeg_codec_registry_names(output: str) -> set[str]:
    names: set[str] = set()
    for raw_line in output.splitlines():
        fields = raw_line.strip().split()
        if len(fields) < 2:
            continue
        flags = fields[0]
        if (
            len(flags) == 6
            and flags[0] in {"A", "S", "V"}
            and set(flags[1:]) <= set(".FSXBD")
            and re.fullmatch(r"[A-Za-z0-9_]+", fields[1])
        ):
            names.add(fields[1])
    return names


def _ffmpeg_format_registry_groups(output: str, *, mode: str) -> list[set[str]]:
    groups: list[set[str]] = []
    for raw_line in output.splitlines():
        fields = raw_line.strip().split()
        if len(fields) < 2:
            continue
        flags = fields[0]
        if flags not in {"D", "E", "DE"} or mode not in flags:
            continue
        groups.append(set(fields[1].split(",")))
    return groups


def _ffmpeg_protocol_registry_names(output: str) -> set[str]:
    names: set[str] = set()
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.endswith(":") or " " in stripped:
            continue
        names.add(stripped)
    return names


def _ffmpeg_filter_registry_names(output: str) -> set[str]:
    names: set[str] = set()
    for raw_line in output.splitlines():
        fields = raw_line.strip().split()
        if len(fields) < 3:
            continue
        flags = fields[0]
        if (
            len(flags) == 2
            and set(flags) <= set(".TS")
            and re.fullmatch(r"[A-Za-z0-9_]+", fields[1])
        ):
            names.add(fields[1])
    return names


def _ffmpeg_plain_registry_names(output: str) -> set[str]:
    names: set[str] = set()
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.endswith(":") or " " in stripped:
            continue
        names.add(stripped)
    return names


def _ffmpeg_configure_tokens(output: str) -> frozenset[str]:
    configuration_lines: list[str] = []
    capturing = False
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("configuration:"):
            capturing = True
            remainder = stripped.partition(":")[2].strip()
            if remainder:
                configuration_lines.append(remainder)
            continue
        if not capturing:
            continue
        if stripped.startswith("libav"):
            break
        if stripped:
            configuration_lines.append(stripped)
    if not configuration_lines:
        return frozenset()
    try:
        return frozenset(
            token
            for token in shlex.split(" ".join(configuration_lines))
            if token.startswith("--")
        )
    except ValueError:
        return frozenset()


def _runtime_media_provenance(
    runner: Any,
) -> dict[str, object]:
    expected_receipts = {
        name: str(path) for name, path in RUNTIME_BUILD_RECEIPT_PATHS.items()
    }
    capture_script = f"""
import hashlib
import json
import shutil
from pathlib import Path

provenance_path = Path({str(RUNTIME_MEDIA_PROVENANCE_PATH)!r})
payload = json.loads(provenance_path.read_text(encoding="utf-8"))
ffmpeg_path_text = shutil.which("ffmpeg") or ""
ffmpeg_path = Path(ffmpeg_path_text) if ffmpeg_path_text else None
expected_receipts = {expected_receipts!r}
observed_receipts = {{}}
for name, expected_path in expected_receipts.items():
    path = Path(expected_path)
    observed_receipts[name] = {{
        "path": expected_path,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file()
        else "",
    }}
print(json.dumps({{
    "payload": payload,
    "observed": {{
        "ffmpeg_path": ffmpeg_path_text,
        "ffmpeg_binary_sha256": hashlib.sha256(ffmpeg_path.read_bytes()).hexdigest()
        if ffmpeg_path is not None and ffmpeg_path.is_file()
        else "",
        "ffmpeg_binary_size": ffmpeg_path.stat().st_size
        if ffmpeg_path is not None and ffmpeg_path.is_file()
        else 0,
        "build_receipts": observed_receipts,
    }},
}}, sort_keys=True, separators=(",", ":")))
"""
    captured = runner(
        "/usr/local/bin/python",
        "-I",
        "-c",
        capture_script,
    )
    if not bool(captured.get("available")):
        return {
            "available": False,
            "path": str(RUNTIME_MEDIA_PROVENANCE_PATH),
            "payload": {},
            "observed": {},
            "reason": "capture_failed",
            "capture": captured,
        }
    try:
        document = json.loads(str(captured.get("output") or ""))
        payload = document["payload"]
        observed = document["observed"]
        if not isinstance(payload, dict) or not isinstance(observed, dict):
            raise TypeError("provenance document must contain object payload and observed")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "available": False,
            "path": str(RUNTIME_MEDIA_PROVENANCE_PATH),
            "payload": {},
            "observed": {},
            "reason": f"invalid_capture:{type(error).__name__}",
            "capture": captured,
        }
    return {
        "available": True,
        "path": str(RUNTIME_MEDIA_PROVENANCE_PATH),
        "payload": payload,
        "observed": observed,
    }


def _is_lower_sha256(value: object) -> bool:
    return bool(_LOWER_SHA256.fullmatch(str(value or "")))


def _exact_string_list(value: object, expected: frozenset[str]) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(expected)
        and set(value) == set(expected)
    )


def _provenance_checks(
    provenance: dict[str, object],
    *,
    configure_tokens: frozenset[str],
    registries: dict[str, set[str]],
) -> dict[str, bool]:
    payload = provenance.get("payload")
    observed = provenance.get("observed")
    if not isinstance(payload, dict) or not isinstance(observed, dict):
        return {"provenance_captured": False}
    ffmpeg = payload.get("ffmpeg")
    glib = payload.get("glib")
    build_receipts = payload.get("build_receipts")
    observed_receipts = observed.get("build_receipts")
    if not isinstance(ffmpeg, dict):
        ffmpeg = {}
    if not isinstance(glib, dict):
        glib = {}
    if not isinstance(build_receipts, dict):
        build_receipts = {}
    if not isinstance(observed_receipts, dict):
        observed_receipts = {}
    declared_registries = ffmpeg.get("registries")
    if not isinstance(declared_registries, dict):
        declared_registries = {}

    declared_receipts_bound = True
    for name, expected_path in RUNTIME_BUILD_RECEIPT_PATHS.items():
        declared = build_receipts.get(name)
        observed_receipt = observed_receipts.get(name)
        if not isinstance(declared, dict) or not isinstance(observed_receipt, dict):
            declared_receipts_bound = False
            continue
        declared_sha256 = str(declared.get("sha256") or "")
        declared_receipts_bound &= (
            str(declared.get("path") or "") == str(expected_path)
            and str(observed_receipt.get("path") or "") == str(expected_path)
            and _is_lower_sha256(declared_sha256)
            and str(observed_receipt.get("sha256") or "") == declared_sha256
        )

    declared_binary_sha256 = str(ffmpeg.get("binary_sha256") or "")
    expected_registry_values = {
        "decoders": FFMPEG_ALLOWED_RUNTIME_DECODERS,
        "demuxers": FFMPEG_ALLOWED_RUNTIME_DEMUXERS,
        "encoders": FFMPEG_ALLOWED_RUNTIME_ENCODERS,
        "muxers": FFMPEG_ALLOWED_RUNTIME_MUXERS,
        "devices": frozenset(),
        "protocols": FFMPEG_REQUIRED_PROTOCOLS,
        "filters": FFMPEG_ALLOWED_RUNTIME_FILTERS,
        "parsers": FFMPEG_ALLOWED_RUNTIME_PARSERS,
        "bitstream_filters": FFMPEG_ALLOWED_RUNTIME_BITSTREAM_FILTERS,
        "hwaccels": FFMPEG_ALLOWED_RUNTIME_HWACCELS,
    }
    declared_registry_exact = all(
        _exact_string_list(declared_registries.get(name), expected)
        for name, expected in expected_registry_values.items()
    )
    observable_registry_names = set(expected_registry_values) - {"parsers"}
    observed_registry_matches_manifest = all(
        _exact_string_list(
            declared_registries.get(name),
            frozenset(registries.get(name, set())),
        )
        for name in observable_registry_names
    )
    expected_glib_values = {
        "version": GLIB_EXPECTED_VERSION,
        "runtime_deb_sha256": GLIB_EXPECTED_RUNTIME_DEB_SHA256,
        "builder_image": GLIB_EXPECTED_BUILDER_IMAGE,
        "snapshot_root": GLIB_EXPECTED_SNAPSHOT_ROOT,
        **GLIB_EXPECTED_SOURCE_HASHES,
    }
    return {
        "provenance_captured": bool(provenance.get("available")),
        "schema_exact": payload.get("schema")
        == "propertyquarry.render_media_provenance.v1"
        and payload.get("version") == 1,
        "ffmpeg_version_exact": ffmpeg.get("version") == FFMPEG_EXPECTED_VERSION,
        "ffmpeg_source_exact": (
            ffmpeg.get("source_url") == FFMPEG_EXPECTED_SOURCE_URL
            and ffmpeg.get("source_sha256") == FFMPEG_EXPECTED_SOURCE_SHA256
            and ffmpeg.get("signature_url") == FFMPEG_EXPECTED_SIGNATURE_URL
            and ffmpeg.get("signature_sha256")
            == FFMPEG_EXPECTED_SIGNATURE_SHA256
            and ffmpeg.get("signing_key_url") == FFMPEG_EXPECTED_SIGNING_KEY_URL
            and ffmpeg.get("signing_key_sha256")
            == FFMPEG_EXPECTED_SIGNING_KEY_SHA256
            and ffmpeg.get("signing_fingerprint")
            == FFMPEG_EXPECTED_SIGNING_FINGERPRINT
        ),
        "ffmpeg_builder_exact": ffmpeg.get("builder_image")
        == FFMPEG_EXPECTED_BUILDER_IMAGE,
        "x264_source_exact": (
            ffmpeg.get("x264_commit") == X264_EXPECTED_COMMIT
            and ffmpeg.get("x264_archive_url") == X264_EXPECTED_ARCHIVE_URL
            and ffmpeg.get("x264_archive_sha256")
            == X264_EXPECTED_ARCHIVE_SHA256
        ),
        "static_gpl_binary_declared": (
            ffmpeg.get("static") is True
            and ffmpeg.get("license") == FFMPEG_EXPECTED_LICENSE
        ),
        "configure_manifest_exact": (
            _exact_string_list(
                ffmpeg.get("configure_enable"),
                FFMPEG_REQUIRED_ENABLE_FLAGS,
            )
            and _exact_string_list(
                ffmpeg.get("configure_disable"),
                FFMPEG_REQUIRED_DISABLE_FLAGS,
            )
            and configure_tokens == FFMPEG_REQUIRED_CONFIGURE_FLAGS
        ),
        "registry_manifest_exact": declared_registry_exact,
        "observed_registries_match_manifest": observed_registry_matches_manifest,
        "binary_sha256_bound": (
            str(observed.get("ffmpeg_path") or "") == "/usr/local/bin/ffmpeg"
            and declared_binary_sha256 == FFMPEG_EXPECTED_BINARY_SHA256
            and str(observed.get("ffmpeg_binary_sha256") or "")
            == declared_binary_sha256
            and ffmpeg.get("binary_size") == FFMPEG_EXPECTED_BINARY_SIZE
            and observed.get("ffmpeg_binary_size") == FFMPEG_EXPECTED_BINARY_SIZE
        ),
        "glib_identity_exact": all(
            glib.get(name) == value for name, value in expected_glib_values.items()
        ),
        "glib_build_contract_exact": (
            glib.get("libmount_disabled") is True
            and "reproducible_builds_observed" not in glib
        ),
        "build_receipts_bound": declared_receipts_bound,
    }


def audit_ffmpeg_encoder(
    runner: Any,
    *,
    require_bounded_surface: bool,
) -> dict[str, object]:
    probes = {
        "version": runner("ffmpeg", "-hide_banner", "-version"),
        "buildconf": runner("ffmpeg", "-hide_banner", "-buildconf"),
        "decoders": runner("ffmpeg", "-hide_banner", "-decoders"),
        "demuxers": runner("ffmpeg", "-hide_banner", "-demuxers"),
        "encoders": runner("ffmpeg", "-hide_banner", "-encoders"),
        "muxers": runner("ffmpeg", "-hide_banner", "-muxers"),
        "devices": runner("ffmpeg", "-hide_banner", "-devices"),
        "protocols": runner("ffmpeg", "-hide_banner", "-protocols"),
        "filters": runner("ffmpeg", "-hide_banner", "-filters"),
        "bitstream_filters": runner("ffmpeg", "-hide_banner", "-bsfs"),
        "hwaccels": runner("ffmpeg", "-hide_banner", "-hwaccels"),
    }
    ffprobe = runner("ffprobe", "-hide_banner", "-version")
    ffplay = runner("ffplay", "-hide_banner", "-version")
    static_linkage = runner("ldd", "/usr/local/bin/ffmpeg")
    decoder_names = _ffmpeg_codec_registry_names(str(probes["decoders"].get("output") or ""))
    demuxer_groups = _ffmpeg_format_registry_groups(
        str(probes["demuxers"].get("output") or ""),
        mode="D",
    )
    demuxer_names = {name for group in demuxer_groups for name in group}
    encoder_names = _ffmpeg_codec_registry_names(str(probes["encoders"].get("output") or ""))
    muxer_groups = _ffmpeg_format_registry_groups(
        str(probes["muxers"].get("output") or ""),
        mode="E",
    )
    muxer_names = {name for group in muxer_groups for name in group}
    input_device_groups = _ffmpeg_format_registry_groups(
        str(probes["devices"].get("output") or ""),
        mode="D",
    )
    output_device_groups = _ffmpeg_format_registry_groups(
        str(probes["devices"].get("output") or ""),
        mode="E",
    )
    device_names = {
        name
        for group in (*input_device_groups, *output_device_groups)
        for name in group
    }
    protocol_names = _ffmpeg_protocol_registry_names(str(probes["protocols"].get("output") or ""))
    filter_names = _ffmpeg_filter_registry_names(str(probes["filters"].get("output") or ""))
    bitstream_filter_names = _ffmpeg_plain_registry_names(
        str(probes["bitstream_filters"].get("output") or "")
    )
    hwaccel_names = _ffmpeg_plain_registry_names(
        str(probes["hwaccels"].get("output") or "")
    )
    build_configuration = str(probes["buildconf"].get("output") or "")
    configure_tokens = _ffmpeg_configure_tokens(build_configuration)
    enable_flags = {token for token in configure_tokens if token.startswith("--enable-")}
    disable_flags = {token for token in configure_tokens if token.startswith("--disable-")}
    version_line = (
        str(probes["version"].get("output") or "").strip().splitlines()[0]
        if str(probes["version"].get("output") or "").strip()
        else ""
    )
    version_exact = bool(
        re.match(
            rf"^ffmpeg version {re.escape(FFMPEG_EXPECTED_VERSION)}(?:\s|$)",
            version_line,
        )
    )
    functional_checks = {
        "rawvideo_decoder": "rawvideo" in decoder_names,
        "rawvideo_demuxer": "rawvideo" in demuxer_names,
        "libx264_encoder": "libx264" in encoder_names,
        "mov_muxer_with_mp4_alias": "mp4" in muxer_names,
        "file_and_pipe_protocols": FFMPEG_REQUIRED_PROTOCOLS <= protocol_names,
        "fps_format_scale_filters": FFMPEG_REQUIRED_FILTERS <= filter_names,
    }
    bounded_checks = {
        "version_exact": version_exact,
        "exact_configure_contract": configure_tokens
        == FFMPEG_REQUIRED_CONFIGURE_FLAGS,
        "explicit_enable_allowlist": enable_flags == FFMPEG_REQUIRED_ENABLE_FLAGS,
        "explicit_disable_contract": disable_flags == FFMPEG_REQUIRED_DISABLE_FLAGS,
        "rawvideo_decoder_only": decoder_names == FFMPEG_ALLOWED_RUNTIME_DECODERS,
        "rawvideo_demuxer_only": demuxer_names == FFMPEG_ALLOWED_RUNTIME_DEMUXERS,
        "libx264_encoder_only": encoder_names == FFMPEG_ALLOWED_RUNTIME_ENCODERS,
        "mov_muxer_only": muxer_names == FFMPEG_ALLOWED_RUNTIME_MUXERS,
        "devices_absent": not device_names,
        "file_and_pipe_protocols_only": protocol_names == FFMPEG_REQUIRED_PROTOCOLS,
        "bounded_filter_surface": filter_names == FFMPEG_ALLOWED_RUNTIME_FILTERS,
        "bounded_bitstream_filter_surface": bitstream_filter_names
        == FFMPEG_ALLOWED_RUNTIME_BITSTREAM_FILTERS,
        "hwaccels_absent": hwaccel_names == FFMPEG_ALLOWED_RUNTIME_HWACCELS,
        "ffprobe_absent": not bool(str(ffprobe.get("path") or "")),
        "ffplay_absent": not bool(str(ffplay.get("path") or "")),
        "static_linkage_observed": (
            bool(str(static_linkage.get("path") or ""))
            and any(
                marker in str(static_linkage.get("output") or "").lower()
                for marker in ("not a dynamic executable", "statically linked")
            )
        ),
    }
    probes_ready = all(bool(row.get("available")) for row in probes.values())
    functional_ready = probes_ready and all(functional_checks.values())
    registries = {
        "decoders": decoder_names,
        "demuxers": demuxer_names,
        "encoders": encoder_names,
        "muxers": muxer_names,
        "devices": device_names,
        "protocols": protocol_names,
        "filters": filter_names,
        "bitstream_filters": bitstream_filter_names,
        "hwaccels": hwaccel_names,
    }
    if require_bounded_surface:
        provenance = _runtime_media_provenance(runner)
        provenance_checks = _provenance_checks(
            provenance,
            configure_tokens=configure_tokens,
            registries=registries,
        )
    else:
        provenance = {
            "available": False,
            "path": str(RUNTIME_MEDIA_PROVENANCE_PATH),
            "status": "not_required_for_functional_host_capability",
        }
        provenance_checks = {"provenance_required": False}
    bounded_surface = (
        functional_ready
        and all(bounded_checks.values())
        and bool(provenance.get("available"))
        and all(provenance_checks.values())
    )
    available = functional_ready and (bounded_surface if require_bounded_surface else True)
    return {
        "available": available,
        "functional_ready": functional_ready,
        "bounded_encoder_only": bounded_surface,
        "bounded_surface_required": require_bounded_surface,
        "capability_posture": "bounded_runtime"
        if require_bounded_surface
        else "functional_host",
        "functional_checks": functional_checks,
        "bounded_checks": bounded_checks,
        "provenance": provenance,
        "provenance_checks": provenance_checks,
        "registries": {
            "decoders": sorted(decoder_names),
            "demuxers": sorted(demuxer_names),
            "encoders": sorted(encoder_names),
            "muxers": sorted(muxer_names),
            "muxer_registry_groups": [sorted(group) for group in muxer_groups],
            "devices": sorted(device_names),
            "protocols": sorted(protocol_names),
            "filters": sorted(filter_names),
            "parsers": sorted(FFMPEG_ALLOWED_RUNTIME_PARSERS)
            if bool(provenance_checks.get("registry_manifest_exact"))
            else [],
            "bitstream_filters": sorted(bitstream_filter_names),
            "hwaccels": sorted(hwaccel_names),
        },
        "configure": {
            "all_flags": sorted(configure_tokens),
            "enable_flags": sorted(enable_flags),
            "disable_flags": sorted(disable_flags),
        },
        "path": str(probes["version"].get("path") or ""),
        "version": version_line[:160],
    }
