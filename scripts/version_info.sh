#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/version_info.sh

Print the current git branch/revision/dirty count plus milestone/version values
from MILESTONE.json when available.
EOF
  exit 0
fi

git_rev="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
git_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
git_dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')"
now_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

milestone="unknown"
version="unknown"
status_summary=""
release_tags=""
if [[ -f "${EA_ROOT}/MILESTONE.json" ]]; then
  milestone="$(python3 - <<'PY'
import json
import pathlib
p = pathlib.Path("MILESTONE.json")
try:
    d = json.loads(p.read_text())
    print(d.get("milestone", "unknown"))
except Exception:
    print("unknown")
PY
)"
  version="$(python3 - <<'PY'
import json
import pathlib
p = pathlib.Path("MILESTONE.json")
try:
    d = json.loads(p.read_text())
    print(d.get("version", "unknown"))
except Exception:
    print("unknown")
PY
)"
  status_summary="$(python3 - <<'PY'
import json
import pathlib

p = pathlib.Path("MILESTONE.json")
try:
    d = json.loads(p.read_text())
    counts = {"planned": 0, "coded": 0, "wired": 0, "tested": 0, "released": 0}
    for row in d.get("capabilities", []):
        status = str(row.get("status", "")).strip().lower()
        if status in counts:
            counts[status] += 1
    print(",".join(f"{key}:{counts[key]}" for key in ("planned", "coded", "wired", "tested", "released")))
except Exception:
    print("")
PY
)"
  release_tags="$(python3 - <<'PY'
import json
import pathlib

p = pathlib.Path("MILESTONE.json")
try:
    d = json.loads(p.read_text())
    print(",".join(str(v) for v in d.get("release_tags", [])))
except Exception:
    print("")
PY
)"
fi

echo "branch=${git_branch}"
echo "revision=${git_rev}"
echo "dirty_files=${git_dirty}"
echo "milestone=${milestone}"
echo "version=${version}"
if [[ -n "${status_summary}" ]]; then
  echo "milestone_status_counts=${status_summary}"
fi
if [[ -n "${release_tags}" ]]; then
  echo "milestone_release_tags=${release_tags}"
fi
echo "generated_utc=${now_utc}"
