from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Iterator
from uuid import uuid4


EXTERNAL_PROCESSING_CONSENT_VERSION = "propertyquarry.external-processing-consent.v2"
EXTERNAL_PROCESSING_CONSENT_AUTHORITY = "authenticated_request_principal"
PROPERTY_APARTMENT_VIDEO_CAPABILITY = "propertyquarry-apartment-video"

_TOKEN_PREFIX = "pqc2"
_MAX_TOKEN_BYTES = 8 * 1024
_MAX_SECRET_BYTES = 4096
_MIN_SECRET_BYTES = 32
_CONSENT_LIFETIME_SECONDS = 15 * 60
_CONSENT_FUTURE_SKEW_SECONDS = 60
_CONSENT_RECORD_RETENTION_SECONDS = 30 * 24 * 60 * 60
_PROPERTY_SLUG = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?\Z")
_STABLE_TOKEN = re.compile(r"\A[A-Za-z0-9._:-]+\Z")
_SHA256_HEX = re.compile(r"\A[a-f0-9]{64}\Z")
_LOCALE = re.compile(r"\A[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?\Z")
_PAYLOAD_FIELDS = frozenset(
    {
        "version",
        "consent_id",
        "issued_at",
        "expires_at",
        "authority",
        "granted",
        "principal_sha256",
        "property_slug",
        "property_id",
        "tour_revision",
        "capability_id",
        "provider_key",
        "work_item_id",
        "locale",
    }
)


def _read_small_secret_file(raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < _MIN_SECRET_BYTES
            or metadata.st_size > _MAX_SECRET_BYTES
        ):
            return ""
        value = os.read(descriptor, _MAX_SECRET_BYTES + 1)
        if len(value) > _MAX_SECRET_BYTES:
            return ""
        return value.decode("utf-8").strip()
    finally:
        os.close(descriptor)


def governed_render_consent_signing_secret() -> str:
    inline = str(
        os.getenv("PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET") or ""
    ).strip()
    if not inline:
        secret_file = str(
            os.getenv("PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET_FILE")
            or ""
        ).strip()
        if secret_file:
            try:
                inline = _read_small_secret_file(secret_file)
            except (OSError, UnicodeError):
                return ""
    encoded = inline.encode("utf-8")
    if (
        len(encoded) < _MIN_SECRET_BYTES
        or len(encoded) > _MAX_SECRET_BYTES
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in inline)
    ):
        return ""
    return inline


def _configured_store_root() -> Path | None:
    raw = str(os.getenv("PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_STORE_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return None
    return path


def _store_path_ready(root: Path | None) -> bool:
    if root is None:
        return False
    try:
        if os.path.lexists(root):
            metadata = root.lstat()
            if not (
                stat.S_ISDIR(metadata.st_mode)
                and not root.is_symlink()
                and metadata.st_uid == os.geteuid()
                and os.access(root, os.R_OK | os.W_OK | os.X_OK)
            ):
                return False
            database_path = root / "consent-receipts.sqlite3"
            if not os.path.lexists(database_path):
                return True
            database_metadata = database_path.lstat()
            if (
                not stat.S_ISREG(database_metadata.st_mode)
                or database_path.is_symlink()
                or database_metadata.st_uid != os.geteuid()
                or database_metadata.st_nlink != 1
                or not os.access(database_path, os.R_OK | os.W_OK)
            ):
                return False
            descriptor = _open_database_descriptor(create=False)
            try:
                connection = sqlite3.connect(
                    f"file:/proc/self/fd/{descriptor}?mode=ro",
                    timeout=1.0,
                    uri=True,
                )
                try:
                    check = connection.execute("PRAGMA quick_check(1)").fetchone()
                    if not check or check[0] != "ok":
                        return False
                    table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'governed_render_consents'"
                    ).fetchone()
                    if table is None:
                        return True
                    columns = {
                        str(row[1])
                        for row in connection.execute(
                            "PRAGMA table_info(governed_render_consents)"
                        ).fetchall()
                    }
                    expected_columns = {
                        "consent_id",
                        "token_sha256",
                        "expires_at",
                        "state",
                        "consumed_at",
                    }
                    return frozenset(columns) in {
                        frozenset(expected_columns),
                        frozenset({*expected_columns, "binding_sha256"}),
                    }
                finally:
                    connection.close()
            finally:
                os.close(descriptor)
        parent = root.parent
        metadata = parent.lstat()
        return stat.S_ISDIR(metadata.st_mode) and not parent.is_symlink() and os.access(parent, os.W_OK | os.X_OK)
    except (OSError, sqlite3.Error):
        return False


def governed_render_consent_runtime_readiness() -> dict[str, object]:
    secret_ready = bool(governed_render_consent_signing_secret())
    store_root = _configured_store_root()
    store_ready = _store_path_ready(store_root)
    blockers: list[str] = []
    if not secret_ready:
        blockers.append("governed_render_consent_signing_secret_missing")
    if store_root is None:
        blockers.append("governed_render_consent_store_missing")
    elif not store_ready:
        blockers.append("governed_render_consent_store_invalid")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": {
            "server_issued_consent_enabled": True,
            "consent_signing_secret_configured": secret_ready,
            "consent_store_configured": store_root is not None,
            "consent_store_ready": store_ready,
            "one_time_transactional_consumption": True,
            "consent_contract_version": EXTERNAL_PROCESSING_CONSENT_VERSION,
        },
    }


def governed_property_video_locale() -> str:
    configured = str(os.getenv("PROPERTYQUARRY_GOVERNED_RENDER_LOCALE") or "en-US").strip()
    return configured if _LOCALE.fullmatch(configured) else ""


def governed_property_video_work_item_id(
    *,
    slug: str,
    provider_key: str,
    tour_revision: str,
) -> str:
    material = json.dumps(
        {
            "property_slug": slug,
            "provider": provider_key,
            "tour_revision": tour_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"{slug}-apartment-video-{digest}"


def _binding_error(
    *,
    principal_id: str,
    property_slug: str,
    property_id: str,
    tour_revision: str,
    provider_key: str,
    work_item_id: str,
    locale: str,
) -> str:
    if not principal_id or len(principal_id.encode("utf-8")) > 2048:
        return "governed_render_principal_invalid"
    if _PROPERTY_SLUG.fullmatch(property_slug) is None:
        return "governed_render_property_slug_invalid"
    if not property_id or len(property_id) > 160 or _STABLE_TOKEN.fullmatch(property_id) is None:
        return "governed_render_property_id_invalid"
    if _SHA256_HEX.fullmatch(tour_revision) is None:
        return "governed_render_tour_revision_invalid"
    if not provider_key or len(provider_key) > 64 or _STABLE_TOKEN.fullmatch(provider_key) is None:
        return "governed_render_provider_invalid"
    if not work_item_id or len(work_item_id) > 180 or _STABLE_TOKEN.fullmatch(work_item_id) is None:
        return "governed_render_work_item_invalid"
    if _LOCALE.fullmatch(locale) is None:
        return "governed_render_locale_invalid"
    expected_work_item_id = governed_property_video_work_item_id(
        slug=property_slug,
        provider_key=provider_key,
        tour_revision=tour_revision,
    )
    if not hmac.compare_digest(expected_work_item_id, work_item_id):
        return "governed_render_work_item_invalid"
    return ""


def _canonical_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > _MAX_TOKEN_BYTES or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("consent_token_encoding_invalid")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("consent_payload_duplicate_key")
        payload[key] = value
    return payload


def _open_database_descriptor(*, create: bool) -> int:
    root = _configured_store_root()
    if root is None:
        raise OSError("consent_store_missing")
    if create:
        try:
            root.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            pass
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(root, directory_flags)
    try:
        metadata = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError("consent_store_invalid")
        if create:
            os.fchmod(directory_descriptor, 0o700)
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        if create:
            try:
                descriptor = os.open(
                    "consent-receipts.sqlite3",
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_descriptor,
                )
            except FileExistsError:
                descriptor = os.open(
                    "consent-receipts.sqlite3",
                    flags,
                    dir_fd=directory_descriptor,
                )
        else:
            descriptor = os.open(
                "consent-receipts.sqlite3",
                flags,
                dir_fd=directory_descriptor,
            )
        database_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(database_metadata.st_mode)
            or database_metadata.st_uid != os.geteuid()
            or database_metadata.st_nlink != 1
        ):
            os.close(descriptor)
            raise OSError("consent_database_invalid")
        if create:
            os.fchmod(descriptor, 0o600)
        return descriptor
    finally:
        os.close(directory_descriptor)


@contextmanager
def _connect_store() -> Iterator[sqlite3.Connection]:
    descriptor = _open_database_descriptor(create=True)
    connection: sqlite3.Connection | None = None
    try:
        # /proc/self/fd anchors SQLite to the already O_NOFOLLOW/openat-validated
        # inode. A path swap after validation cannot redirect the connection.
        connection = sqlite3.connect(
            f"/proc/self/fd/{descriptor}",
            timeout=5.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS governed_render_consents (
                    consent_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL UNIQUE,
                    binding_sha256 TEXT NOT NULL UNIQUE,
                    expires_at INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('pending', 'consumed')),
                    consumed_at INTEGER
                )
                """
            )
            # Recheck only after acquiring the migration write lock. Concurrent
            # replicas then observe one deterministic schema upgrade.
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(governed_render_consents)"
                ).fetchall()
            }
            if "binding_sha256" not in columns:
                # Pre-v2 development receipts cannot prove the full binding
                # needed for no-reissue semantics. Invalidate them on upgrade.
                connection.execute(
                    "ALTER TABLE governed_render_consents ADD COLUMN binding_sha256 TEXT"
                )
                connection.execute("DELETE FROM governed_render_consents")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS governed_render_consents_binding_uq "
                "ON governed_render_consents(binding_sha256)"
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        yield connection
    except BaseException:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()
        os.close(descriptor)


def issue_governed_render_consent_receipt(
    *,
    granted: bool,
    principal_id: str,
    property_slug: str,
    property_id: str,
    tour_revision: str,
    provider_key: str,
    work_item_id: str,
    locale: str,
    now: datetime | None = None,
) -> tuple[str, str]:
    if granted is not True:
        return "", "governed_render_external_processing_consent_not_granted"
    binding_error = _binding_error(
        principal_id=principal_id,
        property_slug=property_slug,
        property_id=property_id,
        tour_revision=tour_revision,
        provider_key=provider_key,
        work_item_id=work_item_id,
        locale=locale,
    )
    if binding_error:
        return "", binding_error
    secret = governed_render_consent_signing_secret()
    if not secret:
        return "", "governed_render_consent_signing_secret_missing"
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_at = int(observed_at.timestamp())
    payload: dict[str, object] = {
        "version": EXTERNAL_PROCESSING_CONSENT_VERSION,
        "consent_id": uuid4().hex,
        "issued_at": issued_at,
        "expires_at": issued_at + _CONSENT_LIFETIME_SECONDS,
        "authority": EXTERNAL_PROCESSING_CONSENT_AUTHORITY,
        "granted": True,
        "principal_sha256": hashlib.sha256(principal_id.encode("utf-8")).hexdigest(),
        "property_slug": property_slug,
        "property_id": property_id,
        "tour_revision": tour_revision,
        "capability_id": PROPERTY_APARTMENT_VIDEO_CAPABILITY,
        "provider_key": provider_key,
        "work_item_id": work_item_id,
        "locale": locale,
    }
    payload_bytes = _canonical_payload(payload)
    signature = hmac.new(
        secret.encode("utf-8"),
        _TOKEN_PREFIX.encode("ascii") + b"\x00" + payload_bytes,
        hashlib.sha256,
    ).digest()
    token = f"{_TOKEN_PREFIX}.{_b64encode(payload_bytes)}.{_b64encode(signature)}"
    token_sha256 = hashlib.sha256(token.encode("ascii")).hexdigest()
    binding_sha256 = hashlib.sha256(
        _canonical_payload(
            {
                key: payload[key]
                for key in (
                    "authority",
                    "principal_sha256",
                    "property_slug",
                    "property_id",
                    "tour_revision",
                    "capability_id",
                    "provider_key",
                    "work_item_id",
                    "locale",
                )
            }
        )
    ).hexdigest()
    try:
        with _connect_store() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM governed_render_consents WHERE expires_at < ?",
                (issued_at - _CONSENT_RECORD_RETENTION_SECONDS,),
            )
            existing = connection.execute(
                "SELECT consent_id, expires_at FROM governed_render_consents "
                "WHERE binding_sha256 = ?",
                (binding_sha256,),
            ).fetchone()
            if existing is not None:
                if int(existing[1]) >= issued_at:
                    connection.rollback()
                    return "", "governed_render_external_processing_consent_already_issued"
                # The old one-time receipt can no longer pass its timestamp
                # gate. Retire its uniqueness lease while retaining the audit
                # row, so a crash/lost response can retry the same deterministic
                # Horizon work item after the 15-minute receipt lifetime.
                retired_binding = hashlib.sha256(
                    f"{binding_sha256}:{existing[0]}:retired".encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE governed_render_consents SET binding_sha256 = ? "
                    "WHERE consent_id = ? AND binding_sha256 = ?",
                    (retired_binding, existing[0], binding_sha256),
                )
            connection.execute(
                "INSERT INTO governed_render_consents "
                "(consent_id, token_sha256, binding_sha256, expires_at, state, consumed_at) "
                "VALUES (?, ?, ?, ?, 'pending', NULL)",
                (
                    payload["consent_id"],
                    token_sha256,
                    binding_sha256,
                    payload["expires_at"],
                ),
            )
            connection.commit()
    except sqlite3.IntegrityError:
        return "", "governed_render_external_processing_consent_already_issued"
    except (OSError, sqlite3.Error):
        return "", "governed_render_consent_store_failed"
    return token, ""


def _decoded_authenticated_payload(token: str) -> tuple[dict[str, object] | None, str]:
    if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
        return None, "governed_render_external_processing_consent_missing"
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        return None, "governed_render_external_processing_consent_invalid"
    secret = governed_render_consent_signing_secret()
    if not secret:
        return None, "governed_render_consent_signing_secret_missing"
    try:
        payload_bytes = _b64decode(parts[1])
        signature = _b64decode(parts[2])
    except (ValueError, UnicodeError):
        return None, "governed_render_external_processing_consent_invalid"
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        _TOKEN_PREFIX.encode("ascii") + b"\x00" + payload_bytes,
        hashlib.sha256,
    ).digest()
    if len(signature) != hashlib.sha256().digest_size or not hmac.compare_digest(signature, expected_signature):
        return None, "governed_render_external_processing_consent_invalid"
    try:
        payload = json.loads(
            payload_bytes.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except (UnicodeError, ValueError):
        return None, "governed_render_external_processing_consent_invalid"
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        return None, "governed_render_external_processing_consent_invalid"
    if _canonical_payload(payload) != payload_bytes:
        return None, "governed_render_external_processing_consent_invalid"
    return dict(payload), ""


def consume_governed_render_consent_receipt(
    *,
    token: str,
    principal_id: str,
    property_slug: str,
    property_id: str,
    tour_revision: str,
    provider_key: str,
    work_item_id: str,
    locale: str,
    now: datetime | None = None,
) -> tuple[dict[str, object] | None, str]:
    binding_error = _binding_error(
        principal_id=principal_id,
        property_slug=property_slug,
        property_id=property_id,
        tour_revision=tour_revision,
        provider_key=provider_key,
        work_item_id=work_item_id,
        locale=locale,
    )
    if binding_error:
        return None, binding_error
    payload, payload_error = _decoded_authenticated_payload(token)
    if payload is None:
        return None, payload_error
    string_bindings = {
        "version": EXTERNAL_PROCESSING_CONSENT_VERSION,
        "authority": EXTERNAL_PROCESSING_CONSENT_AUTHORITY,
        "principal_sha256": hashlib.sha256(principal_id.encode("utf-8")).hexdigest(),
        "property_slug": property_slug,
        "property_id": property_id,
        "tour_revision": tour_revision,
        "capability_id": PROPERTY_APARTMENT_VIDEO_CAPABILITY,
        "provider_key": provider_key,
        "work_item_id": work_item_id,
        "locale": locale,
    }
    if payload.get("granted") is not True or any(
        not isinstance(payload.get(field), str)
        or not hmac.compare_digest(str(payload[field]), expected)
        for field, expected in string_bindings.items()
    ):
        return None, "governed_render_external_processing_consent_binding_mismatch"
    consent_id = payload.get("consent_id")
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(consent_id, str)
        or re.fullmatch(r"[a-f0-9]{32}", consent_id) is None
        or type(issued_at) is not int
        or type(expires_at) is not int
        or expires_at - issued_at != _CONSENT_LIFETIME_SECONDS
    ):
        return None, "governed_render_external_processing_consent_invalid"
    observed_at = int((now or datetime.now(timezone.utc)).astimezone(timezone.utc).timestamp())
    if issued_at > observed_at + _CONSENT_FUTURE_SKEW_SECONDS or expires_at < observed_at:
        return None, "governed_render_external_processing_consent_expired"
    token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        with _connect_store() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE governed_render_consents SET state = 'consumed', consumed_at = ? "
                "WHERE consent_id = ? AND token_sha256 = ? AND expires_at = ? AND state = 'pending'",
                (observed_at, consent_id, token_sha256, expires_at),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT state FROM governed_render_consents WHERE consent_id = ?",
                    (consent_id,),
                ).fetchone()
                connection.rollback()
                if row and row[0] == "consumed":
                    return None, "governed_render_external_processing_consent_replayed"
                return None, "governed_render_external_processing_consent_not_issued"
            connection.commit()
    except (OSError, sqlite3.Error):
        return None, "governed_render_consent_store_failed"
    return payload, ""
