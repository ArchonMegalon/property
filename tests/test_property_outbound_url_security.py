from __future__ import annotations

import socket

import pytest

from ea.app.product import outbound_url_security
from ea.app.product import service as product_service


def _dns_result(address: str, port: int = 443) -> list[tuple[object, ...]]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[object, ...]
    if family == socket.AF_INET6:
        sockaddr = (address, port, 0, 0)
    else:
        sockaddr = (address, port)
    return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]


def test_willhaben_listing_classifier_accepts_exact_and_subdomain_hosts() -> None:
    for host in ("willhaben.at", "www.willhaben.at"):
        url = f"https://{host}/iad/immobilien/d/wohnung-wien-123"
        assert product_service._is_willhaben_property_url(url)
        assert product_service._property_scout_is_supported_listing_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "https://willhaben.at@127.0.0.1/iad/immobilien/d/secret",
        "https://www.willhaben.at.attacker.example/iad/immobilien/d/secret",
    ),
)
def test_willhaben_listing_classifier_rejects_userinfo_and_suffix_spoofing(url: str) -> None:
    assert not product_service._is_willhaben_property_url(url)
    assert not product_service._property_scout_is_supported_listing_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fe80::1]/",
    ),
)
def test_outbound_guard_rejects_local_metadata_and_ipv6_link_local_targets(url: str) -> None:
    with pytest.raises(
        outbound_url_security.OutboundUrlRejected,
        match="outbound_url_address_non_public",
    ):
        outbound_url_security.validate_outbound_url(url)


def test_outbound_guard_rejects_hostname_when_dns_resolves_private() -> None:
    def private_resolver(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        assert host == "www.willhaben.at"
        return _dns_result("10.23.45.67", port)

    with pytest.raises(
        outbound_url_security.OutboundUrlRejected,
        match="outbound_url_address_non_public",
    ):
        outbound_url_security.validate_outbound_url(
            "https://www.willhaben.at/iad/immobilien/d/wohnung-wien-123",
            allowed_hosts=("willhaben.at",),
            resolver=private_resolver,
        )


def test_outbound_guard_accepts_safe_willhaben_host_with_public_dns() -> None:
    def public_resolver(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        assert host == "www.willhaben.at"
        return _dns_result("93.184.216.34", port)

    result = outbound_url_security.validate_outbound_url(
        "https://www.willhaben.at/iad/immobilien/d/wohnung-wien-123",
        allowed_hosts=("willhaben.at",),
        resolver=public_resolver,
    )

    assert result.hostname == "www.willhaben.at"
    assert result.resolved_addresses == ("93.184.216.34",)


def test_outbound_guard_rejects_non_default_port() -> None:
    with pytest.raises(
        outbound_url_security.OutboundUrlRejected,
        match="outbound_url_port_forbidden",
    ):
        outbound_url_security.validate_http_url(
            "https://www.willhaben.at:8443/iad/immobilien/d/wohnung-wien-123",
            allowed_hosts=("willhaben.at",),
        )


def test_guarded_redirect_revalidates_destination_before_second_request() -> None:
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        def close(self) -> None:
            return None

    requests: list[str] = []

    def requester(url: str, **kwargs: object) -> RedirectResponse:
        requests.append(url)
        return RedirectResponse()

    def public_resolver(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        return _dns_result("93.184.216.34", port)

    with pytest.raises(
        outbound_url_security.OutboundUrlRejected,
        match="outbound_url_address_non_public",
    ):
        outbound_url_security.request_get_with_guarded_redirects(
            requester,
            "https://www.willhaben.at/iad/immobilien/d/wohnung-wien-123",
            allowed_hosts=None,
            resolver=public_resolver,
        )

    assert requests == ["https://www.willhaben.at/iad/immobilien/d/wohnung-wien-123"]
