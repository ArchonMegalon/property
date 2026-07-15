from __future__ import annotations

import json
import logging
import sys

from app.logging_utils import RedactingJsonFormatter, redact_log_text


def test_redact_log_text_removes_email_addresses_from_principal_and_error_text() -> None:
    value = "principal=cf-email:person@example.test recipient=other.person+alerts@example.co.uk"

    redacted = redact_log_text(value)

    assert "person@example.test" not in redacted
    assert "other.person+alerts@example.co.uk" not in redacted
    assert redacted.count("[redacted-email]") == 2


def test_json_formatter_redacts_email_addresses_from_message_and_exception() -> None:
    formatter = RedactingJsonFormatter()
    try:
        raise RuntimeError("delivery failed for person@example.test")
    except RuntimeError:
        record = logging.LogRecord(
            name="ea.runner",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="scheduler failed principal=cf-email:person@example.test",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))

    rendered = json.dumps(payload, sort_keys=True)
    assert "person@example.test" not in rendered
    assert "[redacted-email]" in rendered
