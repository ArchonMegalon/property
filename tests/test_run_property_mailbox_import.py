from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_property_mailbox_import.sh"


def test_mailbox_import_script_escapes_json_and_fallback_query(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "headers": dict(self.headers.items()),
                }
            )
            if self.path.startswith("/app/api/people/"):
                self.send_response(404)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env = os.environ.copy()
        env.update(
            {
                "EA_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "EA_API_TOKEN": "secret-token",
                "PERSON_ID": "elisabeth",
                "PRINCIPAL_ID": "principal-1",
                "ACCOUNT_EMAIL": "alice+ops&qa@example.com",
                "CONSENT_NOTE": 'Approved "mailbox"\nimport for housing.',
                "EMAIL_LIMIT": "80",
                "LOOKBACK_DAYS": "30",
            }
        )

        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0
    assert len(requests) == 2

    primary_request = requests[0]
    assert primary_request["path"] == "/app/api/people/elisabeth/preference-profile/mailbox-import"
    primary_body = json.loads(str(primary_request["body"]))
    assert primary_body == {
        "account_email": "alice+ops&qa@example.com",
        "consent_confirmed": True,
        "consent_note": 'Approved "mailbox"\nimport for housing.',
        "email_limit": 80,
        "lookback_days": 30,
    }

    fallback_request = requests[1]
    parsed = urlparse(str(fallback_request["path"]))
    assert parsed.path == "/app/api/signals/google/property-sync"
    assert parse_qs(parsed.query) == {
        "account_email": ["alice+ops&qa@example.com"],
        "email_limit": ["50"],
    }
