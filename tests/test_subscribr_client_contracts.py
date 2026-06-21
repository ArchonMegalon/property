from __future__ import annotations

import io
import urllib.error

import pytest

from app.services.subscribr_client import SubscribrApiError, SubscribrClient


class _FakeResponse:
    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        self._body = body
        self._content_type = content_type

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def getheader(self, name: str, default: str = "") -> str:
        if name.lower() == "content-type":
            return self._content_type
        return default


class _FakeOpener:
    def __init__(self, body: bytes = b'{"ok": true}', *, content_type: str = "application/json") -> None:
        self.body = body
        self.content_type = content_type
        self.requests = []

    def open(self, request, timeout: float):  # noqa: ANN001
        self.requests.append((request, timeout))
        return _FakeResponse(self.body, content_type=self.content_type)


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


def test_subscribr_client_rejects_non_https_base_url() -> None:
    with pytest.raises(SubscribrApiError) as exc:
        SubscribrClient(token="secret-token", opener=_FakeOpener(), base_url="http://subscribr.ai/api/v1")

    assert exc.value.status_code == 400
    assert str(exc.value) == "subscribr_https_required"


def test_subscribr_client_rejects_unapproved_base_host(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_SUBSCRIBR_ALLOWED_HOSTS", raising=False)

    with pytest.raises(SubscribrApiError) as exc:
        SubscribrClient(token="secret-token", opener=_FakeOpener(), base_url="https://evil.example/api/v1")

    assert exc.value.status_code == 400
    assert str(exc.value) == "subscribr_host_not_allowed"


def test_subscribr_client_rejects_base_url_credentials() -> None:
    with pytest.raises(SubscribrApiError) as exc:
        SubscribrClient(token="secret-token", opener=_FakeOpener(), base_url="https://user:pass@subscribr.ai/api/v1")

    assert exc.value.status_code == 400
    assert str(exc.value) == "subscribr_base_url_credentials_forbidden"


def test_subscribr_client_allows_configured_https_base_host(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_SUBSCRIBR_ALLOWED_HOSTS", "content.example")
    opener = _FakeOpener()
    client = SubscribrClient(token="secret-token", opener=opener, base_url="https://content.example/api/v1")

    assert client.get_team() == {"ok": True}
    request, _timeout = opener.requests[0]
    assert request.full_url == "https://content.example/api/v1/team"


def test_subscribr_client_blocks_redirects_without_following_token() -> None:
    class RedirectingOpener:
        def __init__(self) -> None:
            self.requests = []

        def open(self, request, timeout: float):  # noqa: ANN001
            self.requests.append(request)
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "subscribr_redirect_blocked",
                {"Location": "https://evil.example/capture"},
                io.BytesIO(b""),
            )

    opener = RedirectingOpener()
    client = SubscribrClient(token="secret-token", opener=opener, base_url="https://subscribr.ai/api/v1")

    with pytest.raises(SubscribrApiError) as exc:
        client.list_channels()

    assert exc.value.status_code == 302
    assert str(exc.value) == "subscribr_redirect_blocked"
    assert len(opener.requests) == 1
    assert opener.requests[0].full_url == "https://subscribr.ai/api/v1/channels"
    assert opener.requests[0].headers["Authorization"] == "Bearer secret-token"


def test_subscribr_client_rejects_non_json_response() -> None:
    client = SubscribrClient(
        token="secret-token",
        opener=_FakeOpener(b"<html>no</html>", content_type="text/html"),
        base_url="https://subscribr.ai/api/v1",
    )

    with pytest.raises(SubscribrApiError) as exc:
        client.get_team()

    assert exc.value.status_code == 502
    assert str(exc.value) == "subscribr_unexpected_content_type"


def test_subscribr_client_rejects_oversized_response() -> None:
    client = SubscribrClient(
        token="secret-token",
        opener=_FakeOpener(b"{" + (b'"x":' + b'"' + (b"a" * (2 * 1024 * 1024)) + b'"') + b"}"),
        base_url="https://subscribr.ai/api/v1",
    )

    with pytest.raises(SubscribrApiError) as exc:
        client.get_team()

    assert exc.value.status_code == 502
    assert str(exc.value) == "subscribr_response_too_large"
