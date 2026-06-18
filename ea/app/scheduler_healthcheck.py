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
    if role != "scheduler":
        return 0
    path = Path(
        str(
            os.environ.get("EA_SCHEDULER_HEARTBEAT_PATH")
            or "/data/artifacts/propertyquarry-scheduler-heartbeat.json"
        ).strip()
    )
    max_age_seconds = _float_env("EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS", 900.0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed_epoch = float(payload.get("epoch") or 0.0)
    except Exception:
        print(f"scheduler heartbeat unavailable: {path}", file=sys.stderr)
        return 1
    age_seconds = time.time() - observed_epoch
    if age_seconds < 0 or age_seconds > max_age_seconds:
        print(f"scheduler heartbeat stale: age={age_seconds:.1f}s max={max_age_seconds:.1f}s path={path}", file=sys.stderr)
        return 1
    print(f"scheduler heartbeat ok: age={age_seconds:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
