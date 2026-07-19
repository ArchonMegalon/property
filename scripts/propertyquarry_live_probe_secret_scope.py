#!/usr/bin/env python3
"""Environment-safe intake and subprocess scoping for live probe credentials."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Iterator


MAX_RELEASE_PROBE_SECRET_BYTES = 4_096
RELEASE_PROBE_SECRET_ENV_NAMES = (
    "PROPERTYQUARRY_LIVE_PROBE_SECRET",
    "PROPERTYQUARRY_PERFORMANCE_RELEASE_PROBE_SECRET",
)


def release_probe_secret_environment_configured() -> bool:
    return any(os.environ.get(name) for name in RELEASE_PROBE_SECRET_ENV_NAMES)


def read_release_probe_secret_from_stdin(
    parser: argparse.ArgumentParser,
    *,
    enabled: bool,
) -> str:
    """Read one UTF-8 credential without accepting it in argv or the environment."""

    if release_probe_secret_environment_configured():
        parser.error(
            "release-probe credentials must not be supplied in the process environment; "
            "use --release-probe-secret-stdin"
        )
    if not enabled:
        return ""
    # A shell here-string contributes one trailing newline.  Read enough to
    # accept a 4096-byte credential plus that delimiter, but reject any larger
    # stream before the credential is used.
    raw = sys.stdin.buffer.read(MAX_RELEASE_PROBE_SECRET_BYTES + 2)
    if len(raw) > MAX_RELEASE_PROBE_SECRET_BYTES + 1:
        parser.error("release-probe credential stdin exceeds 4096 bytes")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        parser.error("release-probe credential stdin must be UTF-8")
    secret = decoded[:-1] if decoded.endswith("\n") else decoded
    if secret.endswith("\r"):
        secret = secret[:-1]
    if (
        not secret
        or "\x00" in secret
        or "\r" in secret
        or "\n" in secret
        or len(secret.encode("utf-8")) > MAX_RELEASE_PROBE_SECRET_BYTES
    ):
        parser.error("release-probe credential stdin is malformed")
    return secret


@contextlib.contextmanager
def release_probe_secret_environment_scrubbed() -> Iterator[None]:
    """Temporarily prevent probe credentials from reaching a child process."""

    retained = {
        name: os.environ.pop(name)
        for name in RELEASE_PROBE_SECRET_ENV_NAMES
        if name in os.environ
    }
    try:
        yield
    finally:
        for name in RELEASE_PROBE_SECRET_ENV_NAMES:
            os.environ.pop(name, None)
        os.environ.update(retained)


def scrub_release_probe_secret_environment() -> None:
    """Permanently remove probe credentials before any subprocess is started."""

    for name in RELEASE_PROBE_SECRET_ENV_NAMES:
        os.environ.pop(name, None)
