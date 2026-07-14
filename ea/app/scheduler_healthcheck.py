from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


def _float_env(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except Exception:
        value = default
    return max(1.0, value)


def main() -> int:
    role = str(os.environ.get("EA_ROLE") or "").strip().lower()
    if role not in {"scheduler", "worker"}:
        return 0
    env_prefix = "SCHEDULER" if role == "scheduler" else "WORKER"
    default_path = f"/data/artifacts/propertyquarry-{role}-heartbeat.json"
    path = Path(
        str(
            os.environ.get(f"EA_{env_prefix}_HEARTBEAT_PATH")
            or default_path
        ).strip()
    )
    max_age_seconds = _float_env(f"EA_{env_prefix}_HEARTBEAT_MAX_AGE_SECONDS", 900.0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed_epoch = float(payload.get("epoch") or 0.0)
        observed_role = str(payload.get("role") or "").strip().lower()
        observed_pid = int(payload.get("pid") or 0)
    except Exception:
        print(f"{role} heartbeat unavailable: {path}", file=sys.stderr)
        return 1
    if observed_role != role:
        print(
            f"{role} heartbeat role mismatch: observed={observed_role or 'missing'} path={path}",
            file=sys.stderr,
        )
        return 1
    if observed_pid <= 0:
        print(f"{role} heartbeat pid missing: path={path}", file=sys.stderr)
        return 1
    try:
        os.kill(observed_pid, 0)
    except (OSError, ValueError):
        print(f"{role} heartbeat process unavailable: pid={observed_pid} path={path}", file=sys.stderr)
        return 1
    age_seconds = time.time() - observed_epoch
    if age_seconds < 0 or age_seconds > max_age_seconds:
        print(
            f"{role} heartbeat stale: age={age_seconds:.1f}s max={max_age_seconds:.1f}s path={path}",
            file=sys.stderr,
        )
        return 1
    print(f"{role} heartbeat ok: age={age_seconds:.1f}s pid={observed_pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
