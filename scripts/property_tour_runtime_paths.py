from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


DEFAULT_RUNTIME_CONTAINER = "propertyquarry-api"


def manifest_count(root: Path) -> int:
    try:
        resolved = root.expanduser().resolve()
    except OSError:
        return 0
    try:
        return len(list(resolved.glob("*/tour.json"))) if resolved.is_dir() else 0
    except OSError:
        return 0


def best_tour_root(candidates: Iterable[Path]) -> Path | None:
    scored: list[tuple[int, int, Path]] = []
    for index, root in enumerate(candidates):
        candidate = Path(root).expanduser()
        if not candidate.exists():
            continue
        scored.append((manifest_count(candidate), -index, candidate))
    if not scored:
        return None
    return max(scored)[2]


def running_container_public_tour_dir(container_name: str = "") -> Path | None:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return None
    normalized_container = str(
        container_name or os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or DEFAULT_RUNTIME_CONTAINER
    ).strip()
    if not normalized_container:
        return None
    try:
        completed = subprocess.run(
            [
                docker_bin,
                "inspect",
                normalized_container,
                "--format",
                '{{range .Mounts}}{{if eq .Destination "/data/public_property_tours"}}{{println .Source}}{{end}}{{end}}',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    rows = [row.strip() for row in str(completed.stdout or "").splitlines() if row.strip()]
    if not rows:
        return None
    candidate = Path(rows[0]).expanduser()
    return candidate if candidate.exists() else None


def preferred_public_tour_root(
    *,
    configured_root: str | Path = "",
    repo_root: Path | None = None,
    repo_relative_default: str = "state/public_property_tours",
    fallback_root: str | Path = "/docker/property/state/public_property_tours",
    runtime_container: str = "",
) -> Path:
    candidates: list[Path] = []
    raw_configured = str(configured_root or "").strip()
    if raw_configured:
        candidates.append(Path(raw_configured).expanduser())
    if repo_root is not None:
        candidates.append((Path(repo_root).expanduser() / repo_relative_default).expanduser())
    runtime_volume_root = running_container_public_tour_dir(runtime_container)
    if runtime_volume_root is not None:
        candidates.append(runtime_volume_root)
    candidates.append(Path(fallback_root).expanduser())
    preferred = best_tour_root(candidates)
    if preferred is not None:
        return preferred.resolve()
    if raw_configured:
        return Path(raw_configured).expanduser().resolve()
    if repo_root is not None:
        return (Path(repo_root).expanduser() / repo_relative_default).resolve()
    return Path(fallback_root).expanduser().resolve()
