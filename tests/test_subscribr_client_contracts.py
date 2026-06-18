from __future__ import annotations

import io
import urllib.error

import pytest

from app.services.subscribr_client import SubscribrApiError, SubscribrClient


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeOpener:
    def __init__(self, body: bytes = b'{"ok": true}') -> None:
        self.body = body
        self.requests = []

    def open(self, request, timeout: float):  # noqa: ANN001
        self.requests.append((request, timeout))
        return _FakeResponse(self.body)


def test_subscribr_client_uses_bearer_token_without_leaking_it() -> None:
    opener = _FakeOpener()
    client = SubscribrClient(token="secret-token", opener=opener, base_url="https://subscribr.ai/api/v1")

    assert client.get_team() == {"ok": True}

    request, timeout = opener.requests[0]
    assert request.full_url == "https://subscribr.ai/api/v1/team"
    assert request.get_method() == "GET"
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert timeout == 30.0


def test_subscribr_client_respects_retry_after_on_429() -> None:
    class RateLimitedOpener:
        def open(self, request, timeout: float):  # noqa: ANN001
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {"Retry-After": "7"},
                io.BytesIO(b"{}"),
            )

    client = SubscribrClient(token="secret-token", opener=RateLimitedOpener())

    with pytest.raises(SubscribrApiError) as exc:
        client.create_script(channel_id=123, payload={"title": "Demo"})

    assert exc.value.status_code == 429
    assert exc.value.retry_after_seconds == 7
    assert "secret-token" not in str(exc.value)


def test_subscribr_client_requires_token() -> None:
    client = SubscribrClient(token="", opener=_FakeOpener())

    with pytest.raises(SubscribrApiError) as exc:
        client.list_channels()

    assert exc.value.status_code == 503
    assert str(exc.value) == "subscribr_token_not_configured"

