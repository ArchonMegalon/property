from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from ea import property_render_runtime_preflight as preflight
from scripts import generate_property_reconstruction as reconstruction


def _provenance(tmp_path: Path) -> dict[str, object]:
    receipt_root = tmp_path / "receipts"
    recipe_root = tmp_path / "recipes"
    receipt_root.mkdir()
    recipe_root.mkdir()
    receipts: dict[str, dict[str, str]] = {}
    for key, name in (
        ("apk_manifest", "ffmpeg-builder-apk-manifest.txt"),
        ("ffmpeg_recipe", "ffmpeg-build-receipt.json"),
        ("glib_recipe", "glib-build-receipt.json"),
    ):
        path = receipt_root / name
        if key in preflight.EXPECTED_RECIPE_SCRIPTS:
            recipe_name, recipe_sha256 = preflight.EXPECTED_RECIPE_SCRIPTS[key]
            source_recipe = (
                Path(preflight.__file__).parent
                / (
                    "property_render_ffmpeg_build_recipe.sh"
                    if key == "ffmpeg_recipe"
                    else "property_render_glib_build_recipe.sh"
                )
            )
            recipe_path = recipe_root / recipe_name
            recipe_path.write_bytes(source_recipe.read_bytes())
            recipe_path.chmod(0o444)
            assert hashlib.sha256(recipe_path.read_bytes()).hexdigest() == recipe_sha256
            receipt_payload: dict[str, object] = {
                "schema": "propertyquarry.render_media_build_receipt.v1",
                "version": 1,
                "recipe_script_sha256": recipe_sha256,
                **preflight.EXPECTED_BUILD_RECEIPT_CLAIMS[key],
            }
            if key == "ffmpeg_recipe":
                receipt_payload["apk_manifest_sha256"] = receipts[
                    "apk_manifest"
                ]["sha256"]
            path.write_text(
                json.dumps(receipt_payload),
                encoding="utf-8",
            )
        else:
            path.write_text(name + "\n", encoding="utf-8")
        path.chmod(0o444)
        receipts[key] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return {
        "schema": "propertyquarry.render_media_provenance.v1",
        "version": 1,
        "ffmpeg": {
            **{
                field: value
                for (section, field), value in preflight.EXPECTED_SOURCE_VALUES.items()
                if section == "ffmpeg"
            },
            "binary_size_bytes": preflight.EXPECTED_FFMPEG_SIZE,
            "configure_enable": sorted(preflight.EXPECTED_ENABLE_FLAGS),
            "configure_disable": sorted(preflight.EXPECTED_DISABLE_FLAGS),
            "registries": preflight.EXPECTED_REGISTRIES,
            "static": True,
            "license": "GPL-2.0-or-later",
        },
        "glib": {
            **{
                field: value
                for (section, field), value in preflight.EXPECTED_SOURCE_VALUES.items()
                if section == "glib"
            },
            "libmount_disabled": True,
        },
        "playwright": dict(preflight.EXPECTED_PLAYWRIGHT_VALUES),
        "build_receipts": receipts,
    }


def _replace_glb_document(payload: bytes, document: object) -> bytes:
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    binary_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<II", payload, binary_offset)
    binary = payload[binary_offset + 8 : binary_offset + 8 + binary_length]
    encoded_json = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_json += b" " * ((-len(encoded_json)) % 4)
    rebuilt = bytearray(struct.pack("<III", 0x46546C67, 2, 0))
    rebuilt.extend(struct.pack("<II", len(encoded_json), 0x4E4F534A))
    rebuilt.extend(encoded_json)
    rebuilt.extend(struct.pack("<II", len(binary), binary_type))
    rebuilt.extend(binary)
    struct.pack_into("<I", rebuilt, 8, len(rebuilt))
    return bytes(rebuilt)


def _glb_accessor_binary_offset(
    payload: bytes,
    document: dict[str, object],
    accessor_index: int,
) -> int:
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    accessors = document["accessors"]
    buffer_views = document["bufferViews"]
    assert isinstance(accessors, list)
    assert isinstance(buffer_views, list)
    accessor = accessors[accessor_index]
    assert isinstance(accessor, dict)
    view = buffer_views[accessor["bufferView"]]
    assert isinstance(view, dict)
    return (
        20
        + json_length
        + 8
        + int(view.get("byteOffset", 0))
        + int(accessor.get("byteOffset", 0))
    )


def test_read_regular_json_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(source)

    with pytest.raises(preflight.PreflightError, match="provenance_not_regular"):
        preflight._read_regular_json(link)


def test_validate_provenance_rejects_runtime_binary_hash_drift(
    tmp_path: Path,
) -> None:
    document = _provenance(tmp_path)
    ffmpeg = document["ffmpeg"]
    assert isinstance(ffmpeg, dict)
    ffmpeg["binary_sha256"] = "0" * 64

    with pytest.raises(
        preflight.PreflightError,
        match="provenance_ffmpeg_binary_sha256_invalid",
    ):
        preflight._validate_provenance(
            document,
            receipt_root=tmp_path / "receipts",
            recipe_root=tmp_path / "recipes",
        )


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    (
        ("ffmpeg", "builder_image", "alpine:3.22@sha256:" + "0" * 64),
        ("ffmpeg", "signature_verified", False),
        ("glib", "builder_image", "debian:13.6-slim@sha256:" + "0" * 64),
        ("glib", "dsc_signature_verified", False),
    ),
)
def test_validate_provenance_rejects_independent_claim_drift(
    tmp_path: Path,
    section: str,
    field: str,
    replacement: object,
) -> None:
    document = _provenance(tmp_path)
    values = document[section]
    assert isinstance(values, dict)
    values[field] = replacement

    with pytest.raises(
        preflight.PreflightError,
        match=f"provenance_{section}_{field}_invalid",
    ):
        preflight._validate_provenance(
            document,
            receipt_root=tmp_path / "receipts",
            recipe_root=tmp_path / "recipes",
        )


def test_validate_provenance_rejects_rehashed_receipt_claim_drift(
    tmp_path: Path,
) -> None:
    document = _provenance(tmp_path)
    receipts = document["build_receipts"]
    assert isinstance(receipts, dict)
    binding = receipts["ffmpeg_recipe"]
    assert isinstance(binding, dict)
    receipt_path = Path(str(binding["path"]))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["builder_image"] = "alpine:3.22@sha256:" + "0" * 64
    receipt_path.chmod(0o644)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o444)
    binding["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    with pytest.raises(
        preflight.PreflightError,
        match="provenance_ffmpeg_recipe_receipt_builder_image_invalid",
    ):
        preflight._validate_provenance(
            document,
            receipt_root=tmp_path / "receipts",
            recipe_root=tmp_path / "recipes",
        )


def test_validate_provenance_rejects_unsubstantiated_reproducibility_claim(
    tmp_path: Path,
) -> None:
    document = _provenance(tmp_path)
    ffmpeg = document["ffmpeg"]
    assert isinstance(ffmpeg, dict)
    ffmpeg["reproducible_builds_observed"] = 2

    with pytest.raises(
        preflight.PreflightError,
        match="provenance_reproducibility_claim_unsupported",
    ):
        preflight._validate_provenance(
            document,
            receipt_root=tmp_path / "receipts",
            recipe_root=tmp_path / "recipes",
        )


def test_media_provenance_does_not_claim_unbound_reproducible_builds() -> None:
    document = json.loads(
        Path(preflight.__file__)
        .with_name("property_render_media_provenance.json")
        .read_text(encoding="utf-8")
    )

    assert "reproducible_builds_observed" not in document["ffmpeg"]
    assert "reproducible_builds_observed" not in document["glib"]


def test_media_provenance_and_shipped_receipts_match_preflight_authority(
    tmp_path: Path,
) -> None:
    source_root = Path(preflight.__file__).parent
    document = json.loads(
        source_root.joinpath("property_render_media_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_root = tmp_path / "receipts"
    recipe_root = tmp_path / "recipes"
    receipt_root.mkdir()
    recipe_root.mkdir()
    receipt_sources = {
        "apk_manifest": source_root / "property_render_ffmpeg_builder_apk_manifest.txt",
        "ffmpeg_recipe": source_root / "property_render_ffmpeg_build_receipt.json",
        "glib_recipe": source_root / "property_render_glib_build_receipt.json",
    }
    bindings = document["build_receipts"]
    assert isinstance(bindings, dict)
    for name, filename in preflight.EXPECTED_BUILD_RECEIPTS.items():
        target = receipt_root / filename
        target.write_bytes(receipt_sources[name].read_bytes())
        target.chmod(0o444)
        binding = bindings[name]
        assert isinstance(binding, dict)
        binding["path"] = str(target)
    for name, (filename, _sha256) in preflight.EXPECTED_RECIPE_SCRIPTS.items():
        source = source_root / (
            "property_render_ffmpeg_build_recipe.sh"
            if name == "ffmpeg_recipe"
            else "property_render_glib_build_recipe.sh"
        )
        target = recipe_root / filename
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)

    receipt_hashes = preflight._validate_provenance(
        document,
        receipt_root=receipt_root,
        recipe_root=recipe_root,
    )

    assert receipt_hashes == {
        name: bindings[name]["sha256"]
        for name in preflight.EXPECTED_BUILD_RECEIPTS
    }


def test_validate_provenance_rejects_writable_build_receipt(
    tmp_path: Path,
) -> None:
    document = _provenance(tmp_path)
    receipts = document["build_receipts"]
    assert isinstance(receipts, dict)
    binding = receipts["apk_manifest"]
    assert isinstance(binding, dict)
    receipt = Path(str(binding["path"]))
    receipt.chmod(0o664)
    with pytest.raises(preflight.PreflightError, match="provenance_apk_manifest"):
        preflight._validate_provenance(
            document,
            receipt_root=tmp_path / "receipts",
            recipe_root=tmp_path / "recipes",
        )


def test_main_fails_closed_without_leaking_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        preflight,
        "build_preflight_receipt",
        lambda: (_ for _ in ()).throw(RuntimeError("private-path:/operator/home")),
    )

    assert preflight.main([]) == 1

    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "schema": "propertyquarry.render_runtime_preflight.v1",
        "status": "fail",
        "reason": "unexpected_preflight_failure",
    }


def test_validate_generated_glb_accepts_deterministic_generator_output(
    tmp_path: Path,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)

    result = preflight._validate_generated_glb((tmp_path / "model.glb").read_bytes())

    assert result == {
        "accessor_count": 3,
        "binary_bytes": 108,
        "mesh_count": 1,
        "primitive_count": 1,
    }


def test_validate_generated_glb_accepts_multiple_mesh_primitives(
    tmp_path: Path,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = (tmp_path / "model.glb").read_bytes()
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    document["meshes"][0]["primitives"].append(
        dict(document["meshes"][0]["primitives"][0])
    )

    result = preflight._validate_generated_glb(
        _replace_glb_document(payload, document)
    )

    assert result["primitive_count"] == 2


@pytest.mark.parametrize("mutation", ("chunk_order", "asset_version"))
def test_validate_generated_glb_rejects_structural_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = bytearray((tmp_path / "model.glb").read_bytes())
    if mutation == "chunk_order":
        payload[16:20] = (0x004E4942).to_bytes(4, "little")
    else:
        original = b'"version":"2.0"'
        replacement = b'"version":"9.0"'
        offset = payload.index(original)
        payload[offset : offset + len(original)] = replacement

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(bytes(payload))


@pytest.mark.parametrize(
    "mutation",
    (
        "buffer_uri",
        "extensions_required",
        "extensions_used",
        "image_buffer_view",
        "image_uri",
        "material_texture",
        "samplers",
        "sparse_accessor",
        "textures",
    ),
)
def test_validate_generated_glb_rejects_external_or_extended_resources(
    tmp_path: Path,
    mutation: str,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = (tmp_path / "model.glb").read_bytes()
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    if mutation == "buffer_uri":
        document["buffers"][0]["uri"] = "https://attacker.invalid/scene.bin"
    elif mutation == "extensions_required":
        document["extensionsRequired"] = ["EXT_attacker"]
    elif mutation == "extensions_used":
        document["extensionsUsed"] = ["EXT_attacker"]
    elif mutation == "image_buffer_view":
        document["images"] = [{"bufferView": 0, "mimeType": "image/png"}]
    elif mutation == "image_uri":
        document["images"] = [{"uri": "https://attacker.invalid/texture.png"}]
    elif mutation == "material_texture":
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {
            "index": 0
        }
    elif mutation == "samplers":
        document["samplers"] = [{}]
    elif mutation == "sparse_accessor":
        document["accessors"][0]["sparse"] = {"count": 1}
    else:
        document["textures"] = [{"source": 0}]

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(
            _replace_glb_document(payload, document)
        )


@pytest.mark.parametrize("mutation", ("active_scene", "unreachable_node"))
def test_validate_generated_glb_rejects_inactive_or_unreachable_geometry(
    tmp_path: Path,
    mutation: str,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = (tmp_path / "model.glb").read_bytes()
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    if mutation == "active_scene":
        document["scene"] = len(document["scenes"])
    else:
        document["nodes"].append({"mesh": 0, "name": "unreachable"})

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(
            _replace_glb_document(payload, document)
        )


def test_validate_generated_glb_rejects_out_of_range_index_value(
    tmp_path: Path,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = bytearray((tmp_path / "model.glb").read_bytes())
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    primitive = document["meshes"][0]["primitives"][0]
    accessor = document["accessors"][primitive["indices"]]
    view = document["bufferViews"][accessor["bufferView"]]
    binary_data_offset = 20 + json_length + 8
    index_offset = (
        binary_data_offset
        + view.get("byteOffset", 0)
        + accessor.get("byteOffset", 0)
    )
    index_format = {
        5123: "<H",
        5125: "<I",
    }[accessor["componentType"]]
    out_of_range = document["accessors"][
        primitive["attributes"]["POSITION"]
    ]["count"]
    struct.pack_into(index_format, payload, index_offset, out_of_range)

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(bytes(payload))


@pytest.mark.parametrize(
    ("attribute", "component"),
    (("POSITION", float("nan")), ("NORMAL", float("inf"))),
)
def test_validate_generated_glb_rejects_non_finite_geometry(
    tmp_path: Path,
    attribute: str,
    component: float,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = bytearray((tmp_path / "model.glb").read_bytes())
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    primitive = document["meshes"][0]["primitives"][0]
    accessor_index = primitive["attributes"][attribute]
    accessor_offset = _glb_accessor_binary_offset(
        payload,
        document,
        accessor_index,
    )
    struct.pack_into("<f", payload, accessor_offset, component)

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(bytes(payload))


@pytest.mark.parametrize("mutation", ("repeated_indices", "zero_area_positions"))
def test_validate_generated_glb_rejects_degenerate_triangles(
    tmp_path: Path,
    mutation: str,
) -> None:
    reconstruction._write_obj(
        tmp_path,
        width_m=4.0,
        depth_m=3.0,
        height_m=2.5,
        wall_rectangles=[],
    )
    reconstruction._write_glb(tmp_path)
    payload = bytearray((tmp_path / "model.glb").read_bytes())
    json_length, _json_type = struct.unpack_from("<II", payload, 12)
    document = json.loads(payload[20 : 20 + json_length].rstrip(b" \x00"))
    primitive = document["meshes"][0]["primitives"][0]
    if mutation == "repeated_indices":
        accessor_index = primitive["indices"]
        accessor = document["accessors"][accessor_index]
        index_offset = _glb_accessor_binary_offset(
            payload,
            document,
            accessor_index,
        )
        index_format = {5123: "<3H", 5125: "<3I"}[
            accessor["componentType"]
        ]
        struct.pack_into(index_format, payload, index_offset, 0, 0, 0)
    else:
        accessor_index = primitive["attributes"]["POSITION"]
        position_offset = _glb_accessor_binary_offset(
            payload,
            document,
            accessor_index,
        )
        first_position = struct.unpack_from("<3f", payload, position_offset)
        struct.pack_into("<3f", payload, position_offset + 12, *first_position)
        struct.pack_into("<3f", payload, position_offset + 24, *first_position)

    with pytest.raises(preflight.PreflightError, match="direct_glb_preflight_invalid"):
        preflight._validate_generated_glb(bytes(payload))


def _glib_query_runner(
    libmount_result: tuple[int, bytes, bytes],
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    def run(
        argv: Sequence[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        if argv[-1] == "libglib2.0-0t64":
            return subprocess.CompletedProcess(
                argv,
                returncode=0,
                stdout=b"installed\t2.84.4-3~deb13u3+pq1",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            argv,
            returncode=libmount_result[0],
            stdout=libmount_result[1],
            stderr=libmount_result[2],
        )

    return run


def test_glib_package_check_accepts_only_exact_libmount_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "_run",
        _glib_query_runner(
            (
                1,
                b"",
                b"dpkg-query: no packages found matching libmount1\n",
            )
        ),
    )

    preflight._check_glib_package()


@pytest.mark.parametrize(
    ("result", "reason"),
    (
        ((0, b"installed", b""), "libmount_package_present"),
        ((0, b"config-files", b""), "libmount_package_query_failed"),
        ((2, b"", b"database unavailable\n"), "libmount_package_query_failed"),
        ((1, b"", b"ambiguous failure\n"), "libmount_package_absence_unverified"),
        (
            (
                1,
                b"unexpected",
                b"dpkg-query: no packages found matching libmount1\n",
            ),
            "libmount_package_absence_unverified",
        ),
    ),
)
def test_glib_package_check_rejects_noncanonical_libmount_state(
    monkeypatch: pytest.MonkeyPatch,
    result: tuple[int, bytes, bytes],
    reason: str,
) -> None:
    monkeypatch.setattr(preflight, "_run", _glib_query_runner(result))

    with pytest.raises(preflight.PreflightError, match=reason):
        preflight._check_glib_package()


def test_build_preflight_receipt_requires_every_runtime_plane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _provenance(tmp_path)
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(document), encoding="utf-8")
    ffmpeg_path = tmp_path / "ffmpeg"
    ffmpeg_path.write_bytes(b"fake")
    observed: list[str] = []

    monkeypatch.setattr(
        preflight,
        "_validate_provenance",
        lambda _document: observed.append("provenance") or {"apk": "digest"},
    )
    monkeypatch.setattr(
        preflight,
        "_check_ffmpeg_binary",
        lambda path: observed.append(f"binary:{path.name}"),
    )
    monkeypatch.setattr(
        preflight,
        "_check_playwright_artifacts",
        lambda _document: observed.append("playwright_artifacts"),
    )
    monkeypatch.setattr(
        preflight,
        "_check_ffmpeg_capability",
        lambda: observed.append("capability"),
    )
    monkeypatch.setattr(
        preflight,
        "_check_prohibited_commands",
        lambda: observed.append("commands"),
    )
    monkeypatch.setattr(
        preflight,
        "_check_glib_package",
        lambda: observed.append("glib"),
    )
    monkeypatch.setattr(
        preflight,
        "_check_media_functions",
        lambda: observed.append("functions") or {"chromium": "pass"},
    )
    monkeypatch.setattr(
        preflight,
        "_check_admission_runtime",
        lambda: observed.append("admission") or {"distributed_admission": "pass"},
    )

    receipt = preflight.build_preflight_receipt(
        provenance_path=provenance_path,
        ffmpeg_path=ffmpeg_path,
    )

    assert observed == [
        "provenance",
        "playwright_artifacts",
        "binary:ffmpeg",
        "capability",
        "commands",
        "glib",
        "functions",
        "admission",
    ]
    assert receipt["status"] == "pass"
    assert receipt["build_receipt_sha256"] == {"apk": "digest"}
    assert receipt["distributed_admission_runtime"] is True


def test_render_admission_runtime_is_exactly_pinned_to_the_bounded_app_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_version = preflight.importlib.metadata.version

    def pinned_version(name: str) -> str:
        if name in {"psycopg", "psycopg-binary"}:
            return "3.3.4"
        return original_version(name)

    monkeypatch.setattr(preflight.importlib.metadata, "version", pinned_version)

    assert preflight._check_admission_runtime(
        app_root=Path(preflight.__file__).resolve().parents[1]
    ) == {
        "distributed_admission": "pass",
        "w3c_trace_context": "pass",
    }


def test_prohibited_command_check_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "ffprobe" else None,
    )

    with pytest.raises(preflight.PreflightError, match="prohibited_commands_present"):
        preflight._check_prohibited_commands()
