from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Callable


BILLING_DNS_OVER_HTTPS_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def no_proxy_opener(*handlers: object) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), *handlers)


def header_value(headers: dict[str, object], name: str) -> str:
    normalized_name = str(name or "").strip().lower()
    for key, value in headers.items():
        if str(key or "").strip().lower() == normalized_name:
            return str(value or "").strip()
    return ""


def public_dns_host_resolves(host: str, expected_target: str) -> bool:
    normalized_host = str(host or "").strip().lower().rstrip(".")
    normalized_target = str(expected_target or "").strip().lower().rstrip(".")
    if not normalized_host:
        return False
    matched_cname_answer = False
    matched_address_answer = False
    for endpoint in BILLING_DNS_OVER_HTTPS_ENDPOINTS:
        for record_type in ("CNAME", "A", "AAAA"):
            query = urllib.parse.urlencode({"name": normalized_host, "type": record_type})
            request = urllib.request.Request(
                f"{endpoint}?{query}",
                headers={
                    "Accept": "application/dns-json",
                    "User-Agent": "PropertyQuarry-billing-handoff-probe/1.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:
                continue
            for row in payload.get("Answer") or []:
                if not isinstance(row, dict):
                    continue
                answer_name = str(row.get("name") or "").strip().lower().rstrip(".")
                answer_data = str(row.get("data") or "").strip().lower().rstrip(".")
                if answer_name != normalized_host or not answer_data:
                    continue
                row_type = int(row.get("type") or 0)
                if row_type == 5:
                    matched_cname_answer = True
                    if normalized_target and answer_data == normalized_target:
                        return True
                elif row_type in {1, 28}:
                    matched_address_answer = True
    # Cloudflare-proxied CNAMEs intentionally publish edge A/AAAA records. A
    # public address answer is enough to prove the HTTPS handoff host resolves.
    if matched_address_answer:
        return True
    return matched_cname_answer if not normalized_target else False


def https_redirect_host_resolves(
    location: str,
    resolver: Callable[[str, int], object],
    *,
    expected_cname_target: str = "",
) -> bool:
    parsed = urllib.parse.urlparse(str(location or "").strip())
    if parsed.scheme != "https":
        return False
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return False
    try:
        resolver(host, 443)
    except OSError:
        return public_dns_host_resolves(host, expected_cname_target)
    return True


def https_handoff_follow_redirect_url(
    current_url: str,
    redirect_location: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> str:
    next_url = urllib.parse.urljoin(str(current_url or "").strip(), str(redirect_location or "").strip())
    parsed = urllib.parse.urlparse(next_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    normalized_allowed_hosts = {str(host or "").strip().lower() for host in allowed_hosts if str(host or "").strip()}
    current_host = str(urllib.parse.urlparse(str(current_url or "").strip()).hostname or "").strip().lower()
    next_host = str(parsed.hostname or "").strip().lower()
    if normalized_allowed_hosts and next_host not in normalized_allowed_hosts and next_host != current_host:
        return ""
    return next_url


def https_handoff_url_usable(
    location: str,
    *,
    timeout_seconds: float = 8.0,
    visited_urls: tuple[str, ...] = (),
    allowed_hosts: tuple[str, ...] = (),
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(str(location or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return {"ok": False, "status_code": 0, "error": "handoff_url_not_https"}
    request = urllib.request.Request(
        str(location),
        headers={
            "User-Agent": "PropertyQuarry-billing-handoff-probe/1.0",
            "Accept": "text/html,application/json,*/*",
        },
    )
    opener = no_proxy_opener(NoRedirectHandler)
    response_headers: dict[str, object] = {}
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            response_headers = dict(response.headers.items())
            redirect_location = ""
            body = response.read(16_384).decode("utf-8", errors="replace").lower()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        response_headers = dict(exc.headers.items())
        redirect_location = header_value(dict(exc.headers or {}), "Location")
        body = exc.read(16_384).decode("utf-8", errors="replace").lower()
    except Exception as exc:
        return {"ok": False, "status_code": 0, "error": f"{type(exc).__name__}: {exc}"}
    login_target = str(redirect_location or urllib.parse.urlparse(str(location or "")).path or "").lower()
    body_is_login = "<title" in body and "login" in body and ("email" in body or "password" in body)
    requires_login = "/login" in login_target or "login_direct_url" in login_target or body_is_login
    server_header = str(response_headers.get("server") or response_headers.get("Server") or "").strip().lower()
    cloudflare_error_code_match = (
        re.search(r"error code:\s*(\d{3,4})", body, flags=re.IGNORECASE)
        if status_code == 403 and "cloudflare" in server_header and not requires_login
        else None
    )
    cloudflare_error_code = str(cloudflare_error_code_match.group(1) or "").strip() if cloudflare_error_code_match else ""
    usable = 200 <= status_code < 400 and not requires_login and not cloudflare_error_code
    result = {
        "ok": usable,
        "status_code": status_code,
        "redirect_location": redirect_location,
        "error": (
            ""
            if usable
            else (
                "handoff_url_requires_separate_login"
                if requires_login
                else (f"handoff_url_cloudflare_error_{cloudflare_error_code}" if cloudflare_error_code else f"handoff_url_http_{status_code}")
            )
        ),
    }
    if not usable or not redirect_location:
        if redirect_location:
            result["redirect_chain"] = [urllib.parse.urljoin(str(location or "").strip(), redirect_location)]
        return result
    if len(visited_urls) >= 2:
        return {
            **result,
            "ok": False,
            "error": "handoff_url_too_many_redirects",
            "redirect_chain": [urllib.parse.urljoin(str(location or "").strip(), redirect_location)],
        }
    next_url = https_handoff_follow_redirect_url(
        location,
        redirect_location,
        allowed_hosts=allowed_hosts,
    )
    if not next_url:
        return {
            **result,
            "redirect_chain": [urllib.parse.urljoin(str(location or "").strip(), redirect_location)],
        }
    if next_url in visited_urls:
        return {
            **result,
            "ok": False,
            "error": "handoff_url_redirect_loop",
            "redirect_chain": [next_url],
        }
    downstream = https_handoff_url_usable(
        next_url,
        timeout_seconds=timeout_seconds,
        visited_urls=(*visited_urls, str(location or "").strip()),
        allowed_hosts=allowed_hosts,
    )
    redirect_chain = [next_url, *list(downstream.get("redirect_chain") or [])]
    if not downstream.get("ok"):
        return {
            "ok": False,
            "status_code": int(downstream.get("status_code") or status_code),
            "redirect_location": str(downstream.get("redirect_location") or redirect_location),
            "error": str(downstream.get("error") or "handoff_url_requires_separate_login"),
            "redirect_chain": redirect_chain,
        }
    return {
        **downstream,
        "redirect_chain": redirect_chain,
    }


def _admin_login_form_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name in ("action", "tlocation", "string", "website", "rftoken", "newsite"):
        patterns = (
            rf'NAME={name} VALUE="([^"]*)"',
            rf"NAME={name} VALUE='([^']*)'",
            rf'name="{name}" value="([^"]*)"',
            rf"name='{name}' value='([^']*)'",
        )
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                fields[name] = str(match.group(1) or "").strip()
                break
        else:
            fields[name] = ""
    return fields


def _admin_login_form_action(html: str, login_url: str) -> str:
    match = re.search(r"<form[^>]+action=['\"]([^'\"]+)['\"]", html, flags=re.IGNORECASE)
    if not match:
        return ""
    return urllib.parse.urljoin(login_url, str(match.group(1) or "").strip())


def _admin_recovery_href(html: str, login_url: str) -> str:
    for href, label in re.findall(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", html, flags=re.IGNORECASE | re.DOTALL):
        normalized_label = re.sub(r"<[^>]+>", " ", label)
        normalized_label = " ".join(normalized_label.split()).lower()
        if any(token in normalized_label for token in ("forgot", "reset", "password", "username")):
            return urllib.parse.urljoin(login_url, href.strip())
    return ""


def _default_admin_recovery_href(login_url: str, form_action: str = "") -> str:
    for candidate in (form_action, login_url):
        parsed = urllib.parse.urlparse(str(candidate or "").strip())
        host = str(parsed.hostname or "").strip().lower()
        if host.endswith("managemydirectory.com"):
            return urllib.parse.urlunparse(("https", "www.managemydirectory.com", "/admin/login.php", "", "action=retrieve", ""))
    return ""


def billing_admin_login_surface_probe(
    login_url: str = "https://propertyquarry.directoryup.com/admin/login",
    *,
    timeout_seconds: float = 8.0,
) -> dict[str, object]:
    request = urllib.request.Request(
        login_url,
        headers={
            "User-Agent": "PropertyQuarry-billing-admin-probe/1.0",
            "Accept": "text/html,*/*",
        },
    )
    opener = no_proxy_opener()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            html = response.read(32_768).decode("utf-8", errors="replace")
            status_code = int(response.status)
            final_url = str(response.geturl() or login_url).strip()
    except urllib.error.HTTPError as exc:
        html = exc.read(32_768).decode("utf-8", errors="replace")
        status_code = int(exc.code)
        final_url = str(exc.geturl() or login_url).strip()
    except Exception as exc:
        return {
            "configured": False,
            "ok": False,
            "login_url": login_url,
            "status_code": 0,
            "final_url": login_url,
            "error": f"billing_admin_login_probe_failed:{type(exc).__name__}",
        }
    lowered = html.lower()
    form_action = _admin_login_form_action(html, final_url)
    hidden_fields = _admin_login_form_fields(html)
    recovery_href = _admin_recovery_href(html, final_url) or _default_admin_recovery_href(final_url, form_action)
    has_username_field = 'name=username' in lowered or 'name="username"' in lowered or "name='username'" in lowered
    has_password_field = 'name=password' in lowered or 'name="password"' in lowered or "name='password'" in lowered
    recaptcha_required = "recaptcha" in lowered or "g-recaptcha" in lowered or "captcha" in lowered
    ok = status_code == 200 and bool(form_action) and has_username_field and has_password_field
    return {
        "configured": True,
        "ok": ok,
        "login_url": login_url,
        "status_code": status_code,
        "final_url": final_url,
        "form_action": form_action,
        "website_id": hidden_fields.get("website", ""),
        "has_username_field": has_username_field,
        "has_password_field": has_password_field,
        "recaptcha_required": recaptcha_required,
        "recovery_href": recovery_href,
        "error": "" if ok else "billing_admin_login_form_unusable",
    }


def billing_admin_login_attempt(
    *,
    username: str,
    password: str,
    login_url: str = "https://propertyquarry.directoryup.com/admin/login",
    timeout_seconds: float = 8.0,
) -> dict[str, object]:
    normalized_username = str(username or "").strip()
    normalized_password = str(password or "").strip()
    if not normalized_username or not normalized_password:
        return {
            "attempted": False,
            "authenticated": False,
            "error": "billing_admin_credentials_missing",
        }
    surface = billing_admin_login_surface_probe(login_url, timeout_seconds=timeout_seconds)
    if not surface.get("ok"):
        return {
            "attempted": False,
            "authenticated": False,
            "error": str(surface.get("error") or "billing_admin_login_form_unusable"),
            "surface_probe": surface,
        }
    opener = no_proxy_opener(urllib.request.HTTPCookieProcessor())
    initial_request = urllib.request.Request(
        login_url,
        headers={
            "User-Agent": "PropertyQuarry-billing-admin-probe/1.0",
            "Accept": "text/html,*/*",
        },
    )
    with opener.open(initial_request, timeout=timeout_seconds) as response:
        html = response.read(32_768).decode("utf-8", errors="replace")
        effective_login_url = str(response.geturl() or login_url).strip()
    form_action = _admin_login_form_action(html, effective_login_url) or str(surface.get("form_action") or "").strip()
    payload = {
        **_admin_login_form_fields(html),
        "username": normalized_username,
        "password": normalized_password,
    }
    post = urllib.request.Request(
        form_action or effective_login_url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={
            "User-Agent": "PropertyQuarry-billing-admin-probe/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,*/*",
        },
    )
    try:
        with opener.open(post, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            final_url = str(response.geturl() or form_action or effective_login_url).strip()
            raw_body = response.read(32_768).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        final_url = str(exc.geturl() or form_action or effective_login_url).strip()
        raw_body = exc.read(32_768).decode("utf-8", errors="replace")
    body = raw_body.lower()
    invalid = "message=invalid" in final_url.lower() or "administration login" in body
    authenticated = (
        status_code == 200
        and not invalid
        and any(token in body for token in ("logout", "dashboard", "administration", "admin home"))
        and "name=password" not in body
    )
    recovery_href = (
        str(surface.get("recovery_href") or "").strip()
        or _admin_recovery_href(raw_body, final_url)
        or _default_admin_recovery_href(final_url, form_action)
    )
    return {
        "attempted": True,
        "authenticated": authenticated,
        "status_code": status_code,
        "final_url": final_url,
        "recovery_href": recovery_href,
        "error": "" if authenticated else ("billing_admin_invalid_credentials" if invalid else "billing_admin_authentication_failed"),
        "surface_probe": surface,
    }
