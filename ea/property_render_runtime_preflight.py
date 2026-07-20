from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
import os
import shutil
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NoReturn


APP_ROOT = Path("/app")
PROVENANCE_PATH = Path(
    "/usr/local/share/propertyquarry/render-media-provenance.json"
)
FFMPEG_PATH = Path("/usr/local/bin/ffmpeg")
EXPECTED_FFMPEG_SHA256 = (
    "742e5e1808ca6f3e0109567babd422c10adcde207a75ab446279aa7121fb2272"
)
EXPECTED_FFMPEG_SIZE = 3_046_504
EXPECTED_ENABLE_FLAGS = frozenset(
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
EXPECTED_DISABLE_FLAGS = frozenset(
    {
        "--disable-autodetect",
        "--disable-avdevice",
        "--disable-debug",
        "--disable-doc",
        "--disable-everything",
        "--disable-ffplay",
        "--disable-ffprobe",
        "--disable-iconv",
        "--disable-network",
        "--disable-shared",
        "--disable-swresample",
    }
)
EXPECTED_REGISTRIES = {
    "decoders": ["rawvideo"],
    "demuxers": ["rawvideo"],
    "encoders": ["libx264"],
    "muxers": ["mov", "mp4"],
    "devices": [],
    "protocols": ["file", "pipe"],
    "filters": [
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
    ],
    "parsers": ["ac3"],
    "bitstream_filters": ["aac_adtstoasc", "vp9_superframe"],
    "hwaccels": [],
}
EXPECTED_SOURCE_VALUES = {
    ("ffmpeg", "version"): "8.1.2",
    ("ffmpeg", "builder_image"): (
        "alpine:3.22@sha256:"
        "14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
    ),
    ("ffmpeg", "binary_size"): EXPECTED_FFMPEG_SIZE,
    ("ffmpeg", "binary_sha256"): EXPECTED_FFMPEG_SHA256,
    ("ffmpeg", "source_url"): "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz",
    ("ffmpeg", "source_sha256"): (
        "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"
    ),
    ("ffmpeg", "signature_url"): (
        "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz.asc"
    ),
    ("ffmpeg", "signature_sha256"): (
        "0a0963fccd70597838073f3e31b20f4a4d8cc2b5e577472c9a5a1f22624246f8"
    ),
    ("ffmpeg", "signature_verified"): True,
    ("ffmpeg", "signing_key_url"): "https://ffmpeg.org/ffmpeg-devel.asc",
    ("ffmpeg", "signing_key_sha256"): (
        "397b3becedcd5a98769967ff1ff8501ddc89f8368b8f766e4701377d7dbaabe5"
    ),
    ("ffmpeg", "signing_fingerprint"): (
        "FCF986EA15E6E293A5644F10B4322F04D67658D8"
    ),
    ("ffmpeg", "x264_commit"): (
        "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee"
    ),
    ("ffmpeg", "x264_archive_url"): (
        "https://code.videolan.org/videolan/x264/-/archive/"
        "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee/"
        "x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee.tar.gz"
    ),
    ("ffmpeg", "x264_archive_sha256"): (
        "d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50"
    ),
    ("ffmpeg", "x264_upstream_ci_verified"): False,
    ("glib", "version"): "2.84.4-3~deb13u3+pq1",
    ("glib", "builder_image"): (
        "debian:13.6-slim@sha256:"
        "020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd"
    ),
    ("glib", "source_version"): "2.84.4-3~deb13u3",
    ("glib", "snapshot_root"): (
        "https://snapshot.debian.org/archive/debian/20260713T000000Z/"
        "pool/main/g/glib2.0/"
    ),
    ("glib", "dsc_signature_verified"): True,
    ("glib", "runtime_deb_sha256"): (
        "7f78780302454832988b84f1c3c4de31bbbf42a8e3be5dfe69f7980b98384cf8"
    ),
    ("glib", "dsc_sha256"): (
        "4b9e829d82cb5884e6de4250b4c31fd9030ca1be0c29f9b84e9141ee6d9344c1"
    ),
    ("glib", "orig_sha256"): (
        "8a9ea10943c36fc117e253f80c91e477b673525ae45762942858aef57631bb90"
    ),
    ("glib", "unicode_sha256"): (
        "c1742461e8c0e9673a3453a3127671169de9cb0138493e5c916f1b989530efcd"
    ),
    ("glib", "debian_tar_sha256"): (
        "8e35b56abfed5cea96a93d032996efd3a3a5f445a2fc75445f5f42b4d84f42ef"
    ),
}
EXPECTED_BUILD_RECEIPTS = {
    "apk_manifest": "ffmpeg-builder-apk-manifest.txt",
    "ffmpeg_recipe": "ffmpeg-build-receipt.json",
    "glib_recipe": "glib-build-receipt.json",
}
EXPECTED_RECIPE_SCRIPTS = {
    "ffmpeg_recipe": (
        "ffmpeg-build-recipe.sh",
        "a3061e5ce67a5c2223ab5f036c14d4db1eabda17851623d392038de9e209bd92",
    ),
    "glib_recipe": (
        "glib-build-recipe.sh",
        "0063eb0d9a9733461cbfb9257d7549cd18affccc69664a7a48165699e7f3aaba",
    ),
}
EXPECTED_BUILD_RECEIPT_CLAIMS = {
    "ffmpeg_recipe": {
        "builder_image": EXPECTED_SOURCE_VALUES[("ffmpeg", "builder_image")],
        "ffmpeg_binary_sha256": EXPECTED_FFMPEG_SHA256,
        "ffmpeg_binary_size_bytes": EXPECTED_FFMPEG_SIZE,
        "ffmpeg_source_sha256": EXPECTED_SOURCE_VALUES[
            ("ffmpeg", "source_sha256")
        ],
        "ffmpeg_version": EXPECTED_SOURCE_VALUES[("ffmpeg", "version")],
        "signature_verified": True,
        "x264_archive_sha256": EXPECTED_SOURCE_VALUES[
            ("ffmpeg", "x264_archive_sha256")
        ],
        "x264_commit": EXPECTED_SOURCE_VALUES[("ffmpeg", "x264_commit")],
        "x264_upstream_ci_verified": False,
    },
    "glib_recipe": {
        "builder_image": EXPECTED_SOURCE_VALUES[("glib", "builder_image")],
        "dsc_signature_verified": True,
        "libmount_disabled": True,
        "runtime_deb_sha256": EXPECTED_SOURCE_VALUES[
            ("glib", "runtime_deb_sha256")
        ],
        "runtime_version": EXPECTED_SOURCE_VALUES[("glib", "version")],
        "snapshot_root": EXPECTED_SOURCE_VALUES[("glib", "snapshot_root")],
        "source_version": EXPECTED_SOURCE_VALUES[("glib", "source_version")],
    },
}
EXPECTED_PLAYWRIGHT_VALUES = {
    "package_version": "1.60.0",
    "chromium_revision": "1223",
    "chromium_version": "148.0.7778.96",
    "chromium_executable_path": (
        "/ms-playwright/chromium-1223/chrome-linux64/chrome"
    ),
    "chromium_sha256": (
        "adc1c21ceed5c2a67184766376fe816ac03e556cc0ca3f782e8212235fe05c6f"
    ),
    "headless_shell_path": (
        "/ms-playwright/chromium_headless_shell-1223/"
        "chrome-headless-shell-linux64/chrome-headless-shell"
    ),
    "headless_shell_sha256": (
        "7b8e92dca0acf9c24b5974507b3031d6bd18cc009cd431c2595e521430ea747a"
    ),
    "browser_inventory_path": (
        "/usr/local/share/propertyquarry/playwright-browser-inventory.json"
    ),
    "browser_inventory_sha256": (
        "76e9ac14cf412e2c616e09f3e92b831a0a8c23d327e0a5c23d2e7ca6f5a93b93"
    ),
}
PROHIBITED_COMMANDS = (
    "blender",
    "colmap",
    "convert",
    "curl",
    "exiftool",
    "ffplay",
    "ffprobe",
    "gzip",
    "gunzip",
    "magick",
    "meshlab",
    "meshlabserver",
    "runuser",
)
SAFE_ENV = {
    "HOME": "/home/ea",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
}


class PreflightError(RuntimeError):
    pass


def _fail(code: str) -> NoReturn:
    raise PreflightError(code)


def _require(condition: object, code: str) -> None:
    if not condition:
        _fail(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_regular_json(path: Path, *, max_bytes: int = 131_072) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except OSError:
        _fail("provenance_missing")
    _require(stat.S_ISREG(metadata.st_mode), "provenance_not_regular")
    _require(0 < metadata.st_size <= max_bytes, "provenance_size_invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _fail("provenance_open_failed")
    try:
        opened = os.fstat(descriptor)
        _require(
            (opened.st_dev, opened.st_ino, opened.st_size)
            == (metadata.st_dev, metadata.st_ino, metadata.st_size),
            "provenance_changed",
        )
        payload = b""
        while len(payload) <= max_bytes:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload += chunk
        _require(len(payload) == metadata.st_size, "provenance_read_incomplete")
    finally:
        os.close(descriptor)
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _fail("provenance_json_invalid")
    _require(isinstance(decoded, dict), "provenance_root_invalid")
    return decoded


def _mapping(value: object, code: str) -> Mapping[str, object]:
    _require(isinstance(value, dict), code)
    return value  # type: ignore[return-value]


def _validate_provenance(
    document: Mapping[str, object],
    *,
    receipt_root: Path = Path("/usr/local/share/propertyquarry/receipts"),
    recipe_root: Path = Path("/usr/local/share/propertyquarry/recipes"),
) -> dict[str, object]:
    _require(
        document.get("schema") == "propertyquarry.render_media_provenance.v1",
        "provenance_schema_invalid",
    )
    _require(document.get("version") == 1, "provenance_version_invalid")
    _require(
        set(document)
        == {"build_receipts", "ffmpeg", "glib", "playwright", "schema", "version"},
        "provenance_fields_invalid",
    )
    ffmpeg = _mapping(document.get("ffmpeg"), "provenance_ffmpeg_invalid")
    glib = _mapping(document.get("glib"), "provenance_glib_invalid")
    _require(
        "reproducible_builds_observed" not in ffmpeg
        and "reproducible_builds_observed" not in glib,
        "provenance_reproducibility_claim_unsupported",
    )
    sections = {"ffmpeg": ffmpeg, "glib": glib}
    expected_section_fields = {
        "ffmpeg": {
            field
            for section, field in EXPECTED_SOURCE_VALUES
            if section == "ffmpeg"
        }
        | {
            "binary_size_bytes",
            "configure_disable",
            "configure_enable",
            "license",
            "registries",
            "static",
        },
        "glib": {
            field
            for section, field in EXPECTED_SOURCE_VALUES
            if section == "glib"
        }
        | {"libmount_disabled"},
    }
    for section, values in sections.items():
        _require(
            set(values) == expected_section_fields[section],
            f"provenance_{section}_fields_invalid",
        )
    for (section, field), expected in EXPECTED_SOURCE_VALUES.items():
        _require(
            sections[section].get(field) == expected,
            f"provenance_{section}_{field}_invalid",
        )
    _require(ffmpeg.get("binary_size_bytes") == EXPECTED_FFMPEG_SIZE, "provenance_ffmpeg_size_invalid")
    _require(ffmpeg.get("static") is True, "provenance_ffmpeg_static_invalid")
    _require(
        ffmpeg.get("license") == "GPL-2.0-or-later",
        "provenance_ffmpeg_license_invalid",
    )
    _require(
        set(ffmpeg.get("configure_enable") or []) == EXPECTED_ENABLE_FLAGS,
        "provenance_ffmpeg_enable_flags_invalid",
    )
    _require(
        set(ffmpeg.get("configure_disable") or []) == EXPECTED_DISABLE_FLAGS,
        "provenance_ffmpeg_disable_flags_invalid",
    )
    registries = _mapping(
        ffmpeg.get("registries"), "provenance_ffmpeg_registries_invalid"
    )
    _require(
        set(registries) == set(EXPECTED_REGISTRIES),
        "provenance_ffmpeg_registry_fields_invalid",
    )
    for name, expected in EXPECTED_REGISTRIES.items():
        _require(
            sorted(registries.get(name) or []) == sorted(expected),
            f"provenance_ffmpeg_registry_{name}_invalid",
        )
    _require(glib.get("libmount_disabled") is True, "provenance_glib_libmount_invalid")
    receipts = _mapping(
        document.get("build_receipts"), "provenance_build_receipts_invalid"
    )
    _require(
        set(receipts) == set(EXPECTED_BUILD_RECEIPTS),
        "provenance_build_receipt_fields_invalid",
    )
    try:
        receipt_root_metadata = receipt_root.lstat()
        recipe_root_metadata = recipe_root.lstat()
    except OSError:
        _fail("provenance_receipt_roots_missing")
    _require(
        stat.S_ISDIR(receipt_root_metadata.st_mode)
        and not receipt_root.is_symlink()
        and stat.S_ISDIR(recipe_root_metadata.st_mode)
        and not recipe_root.is_symlink(),
        "provenance_receipt_roots_invalid",
    )
    receipt_hashes: dict[str, str] = {}
    for name, filename in EXPECTED_BUILD_RECEIPTS.items():
        binding = _mapping(
            receipts.get(name), f"provenance_{name}_binding_invalid"
        )
        _require(
            set(binding) == {"path", "sha256"},
            f"provenance_{name}_binding_fields_invalid",
        )
        raw_path = str(binding.get("path") or "")
        path = Path(raw_path)
        _require(path.is_absolute(), f"provenance_{name}_invalid")
        _require(path == receipt_root / filename, f"provenance_{name}_location_invalid")
        try:
            metadata = path.lstat()
        except OSError:
            _fail(f"provenance_{name}_missing")
        _require(
            path.parent == receipt_root and not path.is_symlink(),
            f"provenance_{name}_location_invalid",
        )
        _require(
            stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= 1_048_576,
            f"provenance_{name}_file_invalid",
        )
        _require(metadata.st_mode & 0o022 == 0, f"provenance_{name}_writable")
        observed_sha256 = _sha256(path)
        _require(
            binding.get("sha256") == observed_sha256,
            f"provenance_{name}_hash_mismatch",
        )
        receipt_hashes[name] = observed_sha256
        if name in EXPECTED_RECIPE_SCRIPTS:
            recipe_filename, expected_recipe_sha256 = EXPECTED_RECIPE_SCRIPTS[name]
            receipt_document = _read_regular_json(path, max_bytes=65_536)
            _require(
                receipt_document.get("schema")
                == "propertyquarry.render_media_build_receipt.v1"
                and receipt_document.get("version") == 1,
                f"provenance_{name}_receipt_schema_invalid",
            )
            _require(
                receipt_document.get("recipe_script_sha256")
                == expected_recipe_sha256,
                f"provenance_{name}_recipe_declaration_invalid",
            )
            expected_receipt_claims = EXPECTED_BUILD_RECEIPT_CLAIMS[name]
            expected_receipt_fields = {
                "recipe_script_sha256",
                "schema",
                "version",
                *expected_receipt_claims,
            }
            if name == "ffmpeg_recipe":
                expected_receipt_fields.add("apk_manifest_sha256")
            _require(
                set(receipt_document) == expected_receipt_fields,
                f"provenance_{name}_receipt_fields_invalid",
            )
            for field, expected in expected_receipt_claims.items():
                _require(
                    receipt_document.get(field) == expected,
                    f"provenance_{name}_receipt_{field}_invalid",
                )
            if name == "ffmpeg_recipe":
                _require(
                    receipt_document.get("apk_manifest_sha256")
                    == receipt_hashes.get("apk_manifest"),
                    "provenance_ffmpeg_recipe_receipt_apk_manifest_invalid",
                )
            recipe_path = recipe_root / recipe_filename
            try:
                recipe_metadata = recipe_path.lstat()
            except OSError:
                _fail(f"provenance_{name}_recipe_missing")
            _require(
                recipe_path.parent == recipe_root
                and not recipe_path.is_symlink()
                and stat.S_ISREG(recipe_metadata.st_mode)
                and 0 < recipe_metadata.st_size <= 65_536
                and recipe_metadata.st_mode & 0o022 == 0,
                f"provenance_{name}_recipe_file_invalid",
            )
            _require(
                _sha256(recipe_path) == expected_recipe_sha256,
                f"provenance_{name}_recipe_hash_mismatch",
            )
    return receipt_hashes


def _check_playwright_artifacts(document: Mapping[str, object]) -> None:
    playwright = _mapping(
        document.get("playwright"), "provenance_playwright_invalid"
    )
    _require(
        set(playwright) == set(EXPECTED_PLAYWRIGHT_VALUES),
        "provenance_playwright_fields_invalid",
    )
    for field, expected in EXPECTED_PLAYWRIGHT_VALUES.items():
        _require(
            playwright.get(field) == expected,
            f"provenance_playwright_{field}_invalid",
        )
    for path_field, hash_field, max_bytes in (
        ("chromium_executable_path", "chromium_sha256", 512 << 20),
        ("headless_shell_path", "headless_shell_sha256", 512 << 20),
        ("browser_inventory_path", "browser_inventory_sha256", 64 << 20),
    ):
        path = Path(str(playwright[path_field]))
        try:
            resolved = path.resolve(strict=True)
            metadata = path.lstat()
        except OSError:
            _fail(f"playwright_{path_field}_missing")
        _require(resolved == path, f"playwright_{path_field}_symlinked")
        _require(
            stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= max_bytes,
            f"playwright_{path_field}_file_invalid",
        )
        _require(
            metadata.st_mode & 0o022 == 0,
            f"playwright_{path_field}_writable",
        )
        _require(
            _sha256(path) == playwright[hash_field],
            f"playwright_{path_field}_hash_mismatch",
        )
    inventory = _read_regular_json(
        Path(str(playwright["browser_inventory_path"])),
        max_bytes=64 << 20,
    )
    _require(
        inventory.get("schema")
        == "propertyquarry.playwright_browser_inventory.v1"
        and inventory.get("version") == 1,
        "playwright_inventory_schema_invalid",
    )
    _require(
        inventory.get("playwright_package_version") == "1.60.0"
        and inventory.get("chromium_revision") == "1223"
        and inventory.get("chromium_version") == "148.0.7778.96"
        and inventory.get("roots")
        == ["chromium-1223", "chromium_headless_shell-1223"],
        "playwright_inventory_identity_invalid",
    )


def _run(
    argv: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env={**SAFE_ENV, "TZ": os.environ.get("TZ", "UTC")},
            input=input_bytes,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        _fail("runtime_command_failed")


def _check_ffmpeg_binary(ffmpeg_path: Path) -> None:
    try:
        metadata = ffmpeg_path.lstat()
    except OSError:
        _fail("ffmpeg_binary_missing")
    _require(stat.S_ISREG(metadata.st_mode), "ffmpeg_binary_invalid")
    _require(metadata.st_size == EXPECTED_FFMPEG_SIZE, "ffmpeg_binary_size_mismatch")
    _require(_sha256(ffmpeg_path) == EXPECTED_FFMPEG_SHA256, "ffmpeg_binary_hash_mismatch")
    ldd = _run(("/usr/bin/ldd", str(ffmpeg_path)))
    static_output = (ldd.stdout + ldd.stderr).decode("utf-8", "replace").lower()
    _require(
        "not a dynamic executable" in static_output
        or "statically linked" in static_output,
        "ffmpeg_binary_not_static",
    )


def _check_ffmpeg_capability() -> None:
    audit_root = str(Path(__file__).resolve().parent)
    if audit_root not in sys.path:
        sys.path.insert(0, audit_root)
    try:
        import property_render_ffmpeg_validator as audit
    except Exception:
        _fail("ffmpeg_audit_import_failed")
    capability = audit.audit_ffmpeg_encoder(
        audit.capture_local_tool,
        require_bounded_surface=True,
    )
    _require(capability.get("available") is True, "ffmpeg_bounded_capability_failed")
    _require(
        capability.get("bounded_encoder_only") is True,
        "ffmpeg_bounded_surface_failed",
    )


def _check_prohibited_commands() -> None:
    present = [command for command in PROHIBITED_COMMANDS if shutil.which(command)]
    _require(not present, "prohibited_commands_present")


def _check_glib_package() -> None:
    version = _run(
        (
            "/usr/bin/dpkg-query",
            "-W",
            "-f=${db:Status-Status}\t${Version}",
            "libglib2.0-0t64",
        )
    )
    _require(version.returncode == 0, "glib_package_query_failed")
    _require(
        version.stdout.decode("utf-8", "replace")
        == "installed\t2.84.4-3~deb13u3+pq1",
        "glib_package_version_mismatch",
    )
    libmount = _run(
        (
            "/usr/bin/dpkg-query",
            "-W",
            "-f=${db:Status-Status}",
            "libmount1",
        )
    )
    if libmount.returncode == 0 and libmount.stdout == b"installed":
        _fail("libmount_package_present")
    _require(
        libmount.returncode == 1,
        "libmount_package_query_failed",
    )
    _require(
        libmount.stdout == b""
        and libmount.stderr
        == b"dpkg-query: no packages found matching libmount1\n",
        "libmount_package_absence_unverified",
    )


def _glb_integer(value: object, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, "direct_glb_preflight_invalid")
    return value  # type: ignore[return-value]


def _glb_finite_number(
    value: object,
    *,
    minimum: float,
    maximum: float,
) -> float:
    _require(
        type(value) in {int, float}
        and math.isfinite(float(value))
        and minimum <= float(value) <= maximum,
        "direct_glb_preflight_invalid",
    )
    return float(value)


def _validate_generated_glb(payload: bytes) -> dict[str, int]:
    code = "direct_glb_preflight_invalid"
    _require(len(payload) >= 28, code)
    magic, version, declared_length = struct.unpack_from("<III", payload)
    _require((magic, version, declared_length) == (0x46546C67, 2, len(payload)), code)

    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < len(payload):
        _require(offset + 8 <= len(payload), code)
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        offset += 8
        _require(
            chunk_length > 0
            and chunk_length % 4 == 0
            and offset + chunk_length <= len(payload),
            code,
        )
        chunks.append((chunk_type, payload[offset : offset + chunk_length]))
        offset += chunk_length
    _require(offset == len(payload), code)
    _require(
        len(chunks) == 2
        and chunks[0][0] == 0x4E4F534A
        and chunks[1][0] == 0x004E4942,
        code,
    )
    try:
        gltf = json.loads(chunks[0][1].rstrip(b" \x00").decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _fail(code)
    binary_chunk = chunks[1][1]
    _require(isinstance(gltf, dict), code)
    _require(
        set(gltf)
        == {
            "accessors",
            "asset",
            "bufferViews",
            "buffers",
            "materials",
            "meshes",
            "nodes",
            "scene",
            "scenes",
        },
        code,
    )
    asset = gltf.get("asset")
    _require(
        isinstance(asset, dict)
        and set(asset) == {"generator", "version"}
        and asset.get("generator") == "PropertyQuarry deterministic GLB writer"
        and asset.get("version") == "2.0",
        code,
    )

    collections: dict[str, list[object]] = {}
    for name in (
        "scenes",
        "nodes",
        "meshes",
        "materials",
        "accessors",
        "bufferViews",
        "buffers",
    ):
        value = gltf.get(name)
        _require(isinstance(value, list) and bool(value), code)
        collections[name] = value

    buffers = collections["buffers"]
    _require(
        len(buffers) == 1
        and isinstance(buffers[0], dict)
        and set(buffers[0]) == {"byteLength"},
        code,
    )
    declared_binary_bytes = _glb_integer(buffers[0].get("byteLength"), minimum=1)
    _require(0 <= len(binary_chunk) - declared_binary_bytes <= 3, code)

    buffer_views = collections["bufferViews"]
    for view in buffer_views:
        _require(
            isinstance(view, dict)
            and set(view) == {"buffer", "byteLength", "byteOffset", "target"}
            and view.get("buffer") == 0
            and view.get("target") in {34962, 34963},
            code,
        )
        view_offset = _glb_integer(view.get("byteOffset", 0))
        view_length = _glb_integer(view.get("byteLength"), minimum=1)
        _require(view_offset + view_length <= declared_binary_bytes, code)
        _require("byteStride" not in view, code)

    component_widths = {5121: 1, 5123: 2, 5125: 4, 5126: 4}
    type_components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    accessors = collections["accessors"]
    accessor_layouts: list[tuple[int, int, int, int]] = []
    for accessor in accessors:
        _require(
            isinstance(accessor, dict)
            and {"bufferView", "componentType", "count", "type"}
            <= set(accessor)
            <= {
                "bufferView",
                "byteOffset",
                "componentType",
                "count",
                "max",
                "min",
                "type",
            },
            code,
        )
        view_index = _glb_integer(accessor.get("bufferView"))
        _require(view_index < len(buffer_views), code)
        component_type = _glb_integer(accessor.get("componentType"))
        _require(component_type in component_widths, code)
        component_count = type_components.get(accessor.get("type"))
        _require(component_count is not None, code)
        count = _glb_integer(accessor.get("count"), minimum=1)
        accessor_offset = _glb_integer(accessor.get("byteOffset", 0))
        view = buffer_views[view_index]
        _require(isinstance(view, dict), code)
        required_bytes = count * component_widths[component_type] * component_count
        binary_offset = _glb_integer(view.get("byteOffset", 0)) + accessor_offset
        _require(
            accessor_offset + required_bytes
            <= _glb_integer(view.get("byteLength"), minimum=1),
            code,
        )
        _require(
            binary_offset % component_widths[component_type] == 0
            and binary_offset + required_bytes <= declared_binary_bytes,
            code,
        )
        accessor_layouts.append(
            (component_type, count, binary_offset, required_bytes)
        )

    materials = collections["materials"]
    for material in materials:
        _require(
            isinstance(material, dict)
            and set(material) == {"doubleSided", "name", "pbrMetallicRoughness"}
            and material.get("doubleSided") is True
            and isinstance(material.get("name"), str)
            and 1 <= len(str(material.get("name"))) <= 128,
            code,
        )
        pbr = material.get("pbrMetallicRoughness")
        _require(
            isinstance(pbr, dict)
            and set(pbr)
            == {"baseColorFactor", "metallicFactor", "roughnessFactor"},
            code,
        )
        base_color = pbr.get("baseColorFactor")
        _require(isinstance(base_color, list) and len(base_color) == 4, code)
        for component in base_color:
            _glb_finite_number(component, minimum=0.0, maximum=1.0)
        _glb_finite_number(
            pbr.get("metallicFactor"), minimum=0.0, maximum=1.0
        )
        _glb_finite_number(
            pbr.get("roughnessFactor"), minimum=0.0, maximum=1.0
        )

    meshes = collections["meshes"]
    primitive_count = 0
    for mesh in meshes:
        _require(
            isinstance(mesh, dict)
            and set(mesh) == {"name", "primitives"}
            and isinstance(mesh.get("name"), str),
            code,
        )
        primitives = mesh.get("primitives")
        _require(isinstance(primitives, list) and bool(primitives), code)
        primitive_count += len(primitives)
        for primitive in primitives:
            _require(
                isinstance(primitive, dict)
                and set(primitive)
                == {"attributes", "indices", "material", "mode"}
                and primitive.get("mode") == 4,
                code,
            )
            attributes = primitive.get("attributes")
            _require(
                isinstance(attributes, dict)
                and set(attributes) == {"NORMAL", "POSITION"},
                code,
            )
            position_index = _glb_integer(attributes.get("POSITION"))
            normal_index = _glb_integer(attributes.get("NORMAL"))
            indices_index = _glb_integer(primitive.get("indices"))
            _require(
                max(position_index, normal_index, indices_index) < len(accessors),
                code,
            )
            position = accessors[position_index]
            normal = accessors[normal_index]
            indices = accessors[indices_index]
            _require(
                isinstance(position, dict)
                and position.get("componentType") == 5126
                and position.get("type") == "VEC3"
                and isinstance(normal, dict)
                and normal.get("componentType") == 5126
                and normal.get("type") == "VEC3"
                and isinstance(indices, dict)
                and indices.get("componentType") in {5123, 5125}
                and indices.get("type") == "SCALAR"
                and _glb_integer(indices.get("count"), minimum=3) % 3 == 0,
                code,
            )
            position_count = _glb_integer(position.get("count"), minimum=1)
            _require(
                _glb_integer(normal.get("count"), minimum=1) == position_count,
                code,
            )
            (
                position_component_type,
                position_layout_count,
                position_offset,
                position_bytes,
            ) = accessor_layouts[position_index]
            (
                normal_component_type,
                normal_layout_count,
                normal_offset,
                normal_bytes,
            ) = accessor_layouts[normal_index]
            index_component_type, index_count, index_offset, index_bytes = (
                accessor_layouts[indices_index]
            )
            _require(
                position_component_type == 5126
                and normal_component_type == 5126
                and position_layout_count == position_count
                and normal_layout_count == position_count,
                code,
            )
            position_view = buffer_views[
                _glb_integer(position.get("bufferView"))
            ]
            normal_view = buffer_views[_glb_integer(normal.get("bufferView"))]
            index_view = buffer_views[_glb_integer(indices.get("bufferView"))]
            _require(
                isinstance(position_view, dict)
                and position_view.get("target") == 34962
                and isinstance(normal_view, dict)
                and normal_view.get("target") == 34962
                and isinstance(index_view, dict)
                and index_view.get("target") == 34963,
                code,
            )
            index_format = {5123: "<H", 5125: "<I"}[index_component_type]
            try:
                position_values = tuple(
                    struct.iter_unpack(
                        "<3f",
                        binary_chunk[
                            position_offset : position_offset + position_bytes
                        ],
                    )
                )
                normal_values = tuple(
                    struct.iter_unpack(
                        "<3f",
                        binary_chunk[normal_offset : normal_offset + normal_bytes],
                    )
                )
                index_values = tuple(
                    value[0]
                    for value in struct.iter_unpack(
                        index_format,
                        binary_chunk[index_offset : index_offset + index_bytes],
                    )
                )
                _require(
                    len(position_values) == position_count
                    and len(normal_values) == position_count
                    and len(index_values) == index_count
                    and all(
                        math.isfinite(component)
                        for vector in (*position_values, *normal_values)
                        for component in vector
                    )
                    and all(index < position_count for index in index_values),
                    code,
                )
            except struct.error:
                _fail(code)
            for triangle_offset in range(0, len(index_values), 3):
                first, second, third = index_values[
                    triangle_offset : triangle_offset + 3
                ]
                _require(len({first, second, third}) == 3, code)
                first_position = position_values[first]
                second_position = position_values[second]
                third_position = position_values[third]
                first_edge = tuple(
                    second_position[axis] - first_position[axis]
                    for axis in range(3)
                )
                second_edge = tuple(
                    third_position[axis] - first_position[axis]
                    for axis in range(3)
                )
                cross_product = (
                    first_edge[1] * second_edge[2]
                    - first_edge[2] * second_edge[1],
                    first_edge[2] * second_edge[0]
                    - first_edge[0] * second_edge[2],
                    first_edge[0] * second_edge[1]
                    - first_edge[1] * second_edge[0],
                )
                area_squared = sum(component * component for component in cross_product)
                _require(math.isfinite(area_squared) and area_squared > 0.0, code)
            material_index = _glb_integer(primitive.get("material"))
            _require(
                material_index < len(materials)
                and isinstance(materials[material_index], dict),
                code,
            )

    nodes = collections["nodes"]
    unsupported_node_fields = {
        "camera",
        "children",
        "matrix",
        "rotation",
        "scale",
        "skin",
        "translation",
        "weights",
    }
    for node in nodes:
        _require(
            isinstance(node, dict)
            and set(node) == {"mesh", "name"}
            and isinstance(node.get("name"), str)
            and not unsupported_node_fields.intersection(node),
            code,
        )
        _require(_glb_integer(node.get("mesh")) < len(meshes), code)
    scenes = collections["scenes"]
    for scene in scenes:
        _require(isinstance(scene, dict) and set(scene) == {"nodes"}, code)
        scene_nodes = scene.get("nodes")
        _require(isinstance(scene_nodes, list) and bool(scene_nodes), code)
        _require(
            all(_glb_integer(node_index) < len(nodes) for node_index in scene_nodes),
            code,
        )
    active_scene_index = _glb_integer(gltf.get("scene"))
    _require(active_scene_index < len(scenes), code)
    active_scene = scenes[active_scene_index]
    _require(isinstance(active_scene, dict), code)
    active_nodes = active_scene.get("nodes")
    _require(isinstance(active_nodes, list) and bool(active_nodes), code)
    active_node_indices = [_glb_integer(value) for value in active_nodes]
    _require(
        len(set(active_node_indices)) == len(active_node_indices)
        and sorted(active_node_indices) == list(range(len(nodes))),
        code,
    )
    active_mesh_indices: list[int] = []
    for node_index in active_node_indices:
        node = nodes[node_index]
        _require(isinstance(node, dict), code)
        active_mesh_indices.append(_glb_integer(node.get("mesh")))
    _require(sorted(active_mesh_indices) == list(range(len(meshes))), code)
    return {
        "accessor_count": len(accessors),
        "binary_bytes": declared_binary_bytes,
        "mesh_count": len(meshes),
        "primitive_count": primitive_count,
    }


def _check_media_functions() -> dict[str, object]:
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    try:
        from PIL import Image
    except Exception:
        _fail("pillow_import_failed")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        _fail("playwright_import_failed")
    try:
        from scripts import generate_property_reconstruction as reconstruction
    except Exception:
        _fail("reconstruction_import_failed")
    try:
        from scripts import property_render_video_probe as render_video_probe
    except Exception:
        _fail("render_video_probe_import_failed")
    try:
        from scripts.propertyquarry_playwright_runtime import (
            playwright_chromium_launch_kwargs,
        )
    except Exception:
        _fail("playwright_helper_import_failed")

    _require(
        importlib.metadata.version("playwright") == "1.60.0",
        "playwright_package_version_mismatch",
    )

    with io.BytesIO() as image_payload:
        Image.new("RGB", (4, 4), (18, 52, 86)).save(image_payload, format="PNG")
        _require(image_payload.getvalue().startswith(b"\x89PNG\r\n\x1a\n"), "pillow_png_failed")

    ssl_context = ssl.create_default_context()
    _require(bool(ssl_context.get_ca_certs()), "ca_store_empty")

    with tempfile.TemporaryDirectory(prefix="pq-render-preflight-", dir="/tmp") as raw:
        root = Path(raw)
        model_dir = root / "model"
        model_dir.mkdir()
        reconstruction._write_obj(
            model_dir,
            width_m=4.0,
            depth_m=3.0,
            height_m=2.5,
            wall_rectangles=[],
        )
        glb = reconstruction._write_glb(model_dir)
        _require(glb.get("status") == "generated", "direct_glb_preflight_failed")
        glb_payload = (model_dir / "model.glb").read_bytes()
        glb_validation = _validate_generated_glb(glb_payload)

        mp4_path = root / "preflight.mp4"
        frame = Image.new("RGB", (64, 64), (42, 96, 160))
        try:
            completed = reconstruction._encode_rgb24_mp4(
                frames=(frame for _index in range(12)),
                target=mp4_path,
                frame_size=(64, 64),
                input_fps=12.0,
                output_fps=12,
                expected_input_frame_count=12,
                expected_frame_count=12,
                crf=18,
                timeout_seconds=30,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            _fail("ffmpeg_encode_preflight_failed")
        finally:
            frame.close()
        _require(completed.returncode == 0, "ffmpeg_encode_preflight_failed")
        try:
            video_probe = render_video_probe.probe_local_video(mp4_path)
            duration = float(video_probe["duration_seconds"])
            probed_size = int(video_probe["size_bytes"])
        except (KeyError, TypeError, ValueError, SystemExit):
            _fail("render_video_probe_preflight_failed")
        _require(abs(duration - 1.0) <= 0.05, "ffmpeg_duration_preflight_failed")
        _require(
            probed_size == mp4_path.stat().st_size,
            "magicfit_acceptance_video_size_preflight_failed",
        )

        preflight_html = root / "preflight.html"
        glb_url_path = "/model/model.glb"
        preflight_url_path = "/preflight.html"
        three_source = APP_ROOT / "vendor/three/0.167.1/three.module.js"
        try:
            three_source_metadata = three_source.lstat()
            _require(
                stat.S_ISREG(three_source_metadata.st_mode)
                and not three_source.is_symlink()
                and _sha256(three_source)
                == reconstruction.THREE_MODULE_SOURCE_SHA256,
                "threejs_source_invalid",
            )
            shutil.copyfile(three_source, root / "three.module.js")
        except PreflightError:
            raise
        except OSError:
            _fail("threejs_source_invalid")
        preflight_html.write_text(
            """<!doctype html>
<meta charset="utf-8">
<canvas id="proof" width="320" height="240"></canvas>
<script type="importmap">
{"imports":{"three":"/three.module.js"}}
</script>
<script type="module">
const canvas = document.querySelector("#proof");
try {
  const THREE = await import("three");
  const requireValue = (condition, reason) => {
    if (!condition) throw new Error(reason);
  };
  const response = await fetch(""" + json.dumps(glb_url_path) + """, {cache: "no-store"});
  requireValue(response.ok, "glb_fetch_failed");
  const glb = await response.arrayBuffer();
  const header = new DataView(glb);
  requireValue(
    glb.byteLength >= 28 &&
      header.getUint32(0, true) === 0x46546c67 &&
      header.getUint32(4, true) === 2 &&
      header.getUint32(8, true) === glb.byteLength,
    "glb_header_invalid",
  );
  const jsonLength = header.getUint32(12, true);
  requireValue(jsonLength % 4 === 0 && header.getUint32(16, true) === 0x4e4f534a, "glb_json_invalid");
  const jsonEnd = 20 + jsonLength;
  requireValue(jsonEnd + 8 <= glb.byteLength, "glb_json_invalid");
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(glb, 20, jsonLength)).trim());
  const binaryLength = header.getUint32(jsonEnd, true);
  requireValue(
    binaryLength % 4 === 0 &&
      header.getUint32(jsonEnd + 4, true) === 0x004e4942 &&
      jsonEnd + 8 + binaryLength === glb.byteLength,
    "glb_binary_invalid",
  );
  const binaryOffset = jsonEnd + 8;
  const componentTypes = new Map([
    [5121, Uint8Array],
    [5123, Uint16Array],
    [5125, Uint32Array],
    [5126, Float32Array],
  ]);
  const componentCounts = new Map([["SCALAR", 1], ["VEC2", 2], ["VEC3", 3], ["VEC4", 4]]);
  const loadAccessor = (index) => {
    const accessor = document.accessors[index];
    const view = document.bufferViews[accessor.bufferView];
    const Constructor = componentTypes.get(accessor.componentType);
    const itemSize = componentCounts.get(accessor.type);
    requireValue(Constructor && itemSize && !view.byteStride, "glb_accessor_invalid");
    const byteOffset = binaryOffset + (view.byteOffset || 0) + (accessor.byteOffset || 0);
    return {
      array: new Constructor(glb, byteOffset, accessor.count * itemSize),
      itemSize,
    };
  };
  const renderer = new THREE.WebGLRenderer({canvas, antialias: false});
  renderer.setSize(320, 240, false);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x102030);
  const camera = new THREE.PerspectiveCamera(45, 4 / 3, 0.01, 1000);
  const model = new THREE.Group();
  const activeSceneDocument = document.scenes[document.scene];
  requireValue(activeSceneDocument && Array.isArray(activeSceneDocument.nodes), "glb_scene_invalid");
  let meshCount = 0;
  let primitiveCount = 0;
  for (const nodeIndex of activeSceneDocument.nodes) {
    const nodeDocument = document.nodes[nodeIndex];
    const meshDocument = document.meshes[nodeDocument.mesh];
    requireValue(meshDocument && Array.isArray(meshDocument.primitives), "glb_node_invalid");
    meshCount += 1;
    for (const primitive of meshDocument.primitives) {
      const positions = loadAccessor(primitive.attributes.POSITION);
      const normals = loadAccessor(primitive.attributes.NORMAL);
      const indices = loadAccessor(primitive.indices);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions.array, positions.itemSize));
      geometry.setAttribute("normal", new THREE.BufferAttribute(normals.array, normals.itemSize));
      geometry.setIndex(new THREE.BufferAttribute(indices.array, indices.itemSize));
      geometry.computeBoundingSphere();
      const color = document.materials?.[primitive.material]?.pbrMetallicRoughness?.baseColorFactor;
      const material = new THREE.MeshStandardMaterial({
        color: Array.isArray(color) ? new THREE.Color(color[0], color[1], color[2]) : 0x62a0ea,
        side: THREE.DoubleSide,
      });
      model.add(new THREE.Mesh(geometry, material));
      primitiveCount += 1;
    }
  }
  requireValue(primitiveCount > 0, "glb_mesh_missing");
  scene.add(model);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x404040, 2));
  const box = new THREE.Box3().setFromObject(model);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const distance = Math.max(size.x, size.y, size.z, 1) * 2.5;
  camera.position.set(center.x + distance, center.y + distance, center.z + distance);
  camera.lookAt(center);
  renderer.render(scene, camera);
  window.__pqRenderProof = {
    ready: true,
    glbLoaded: true,
    glbBytes: glb.byteLength,
    glbAccessorCount: document.accessors.length,
    meshCount,
    primitiveCount,
    triangles: renderer.info.render.triangles,
    webglVersion: String(renderer.getContext().getParameter(renderer.getContext().VERSION) || ""),
  };
} catch (error) {
  window.__pqRenderProof = {ready: false, error: error && error.name ? error.name : "render_failed"};
}
</script>
""",
            encoding="utf-8",
        )
        try:
            with reconstruction._serve_directory(root) as base_url:
                with sync_playwright() as playwright:
                    launch = playwright_chromium_launch_kwargs(playwright)
                    browser = playwright.chromium.launch(**launch)
                    try:
                        page = browser.new_page()
                        page.goto(
                            f"{base_url}{preflight_url_path}",
                            wait_until="domcontentloaded",
                        )
                        page.wait_for_function(
                            "() => window.__pqRenderProof !== undefined",
                            timeout=30_000,
                        )
                        render_proof = page.evaluate("() => window.__pqRenderProof")
                        _require(
                            isinstance(render_proof, dict)
                            and render_proof.get("ready") is True
                            and render_proof.get("glbLoaded") is True
                            and render_proof.get("glbBytes") == len(glb_payload)
                            and render_proof.get("glbAccessorCount")
                            == glb_validation["accessor_count"]
                            and render_proof.get("meshCount")
                            == glb_validation["mesh_count"]
                            and render_proof.get("primitiveCount")
                            == glb_validation["primitive_count"],
                            "chromium_threejs_glb_preflight_failed",
                        )
                        _require(
                            int(render_proof.get("meshCount") or 0) > 0
                            and int(render_proof.get("primitiveCount") or 0) > 0
                            and int(render_proof.get("triangles") or 0) > 0
                            and "webgl" in str(
                                render_proof.get("webglVersion") or ""
                            ).lower(),
                            "chromium_webgl_preflight_failed",
                        )
                    finally:
                        browser.close()
        except PreflightError:
            raise
        except Exception:
            _fail("chromium_launch_preflight_failed")
    return {
        "glb": "pass",
        "offline_render_video_probe": "pass",
        "mp4_duration_seconds": 1.0,
        "chromium": "pass",
        "threejs_glb_webgl": "pass",
    }


def _check_admission_runtime(
    *,
    app_root: Path = APP_ROOT,
) -> dict[str, str]:
    ea_root = (app_root / "ea").resolve()
    if str(ea_root) not in sys.path:
        sys.path.insert(0, str(ea_root))
    try:
        import psycopg  # noqa: F401
        from app import observability
        from app.services import admission_control
    except Exception:
        _fail("distributed_admission_import_failed")

    expected_sources = {
        Path(admission_control.__file__).resolve(): (
            ea_root / "app/services/admission_control.py"
        ).resolve(),
        Path(observability.__file__).resolve(): (
            ea_root / "app/observability.py"
        ).resolve(),
    }
    _require(
        all(observed == expected for observed, expected in expected_sources.items()),
        "distributed_admission_source_mismatch",
    )
    _require(
        importlib.metadata.version("psycopg") == "3.3.4"
        and importlib.metadata.version("psycopg-binary") == "3.3.4",
        "distributed_admission_package_version_mismatch",
    )
    backend = admission_control.MemoryAdmissionBackend()
    backend.probe()
    trace = observability.new_server_trace_context()
    _require(
        bool(trace.traceparent) and len(trace.trace_id) == 32,
        "distributed_admission_observability_failed",
    )
    return {
        "distributed_admission": "pass",
        "w3c_trace_context": "pass",
    }


def build_preflight_receipt(
    *,
    provenance_path: Path = PROVENANCE_PATH,
    ffmpeg_path: Path = FFMPEG_PATH,
) -> dict[str, object]:
    provenance = _read_regular_json(provenance_path)
    receipt_hashes = _validate_provenance(provenance)
    _check_playwright_artifacts(provenance)
    _check_ffmpeg_binary(ffmpeg_path)
    _check_ffmpeg_capability()
    _check_prohibited_commands()
    _check_glib_package()
    functions = _check_media_functions()
    functions.update(_check_admission_runtime())
    return {
        "schema": "propertyquarry.render_runtime_preflight.v1",
        "status": "pass",
        "bounded_ffmpeg": True,
        "direct_glb": True,
        "playwright_chromium": True,
        "glib_without_libmount": True,
        "distributed_admission_runtime": True,
        "prohibited_commands_absent": True,
        "ffmpeg_sha256": EXPECTED_FFMPEG_SHA256,
        "build_receipt_sha256": receipt_hashes,
        "functional_checks": functions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    if list(sys.argv[1:] if argv is None else argv):
        print(
            json.dumps(
                {
                    "schema": "propertyquarry.render_runtime_preflight.v1",
                    "status": "fail",
                    "reason": "arguments_forbidden",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 64
    try:
        receipt = build_preflight_receipt()
    except PreflightError as error:
        receipt = {
            "schema": "propertyquarry.render_runtime_preflight.v1",
            "status": "fail",
            "reason": str(error),
        }
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 1
    except Exception:
        receipt = {
            "schema": "propertyquarry.render_runtime_preflight.v1",
            "status": "fail",
            "reason": "unexpected_preflight_failure",
        }
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
