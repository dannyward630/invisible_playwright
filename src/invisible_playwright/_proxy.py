"""Proxy translation shared by sync and async launchers.

SOCKS proxies are driven entirely by the patched Firefox prefs (the
``nsProtocolProxyService`` patch reads ``network.proxy.socks_username``
and ``socks_password``). HTTP/HTTPS proxies go through Playwright's own
``proxy=`` kwarg so it can negotiate Basic auth.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests


_SOCKS_SCHEMES = ("socks5://", "socks4://", "socks://")
_DEFAULT_TIMEZONE_ENDPOINT = "https://ipapi.co/timezone/"


def configure_proxy(
    proxy: Optional[Dict[str, str]],
    prefs: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """Mutate ``prefs`` for SOCKS auth; return what to pass to Playwright.

    * ``None`` proxy → returns ``None``.
    * SOCKS proxy → writes the auth prefs and returns ``None`` (Playwright
      gets nothing; Firefox does the rest).
    * HTTP / HTTPS proxy → returns the dict unchanged for Playwright.
    """
    if not proxy:
        return None

    server = (proxy.get("server") or "").strip()
    if not server or server.lower() == "direct://":
        return None
    if not _is_socks_scheme(server):
        return proxy

    host_port = _strip_scheme(server)
    if ":" not in host_port:
        return None  # malformed, drop silently

    host, port_str = host_port.rsplit(":", 1)
    prefs["network.proxy.type"]            = 1
    prefs["network.proxy.socks"]           = host
    prefs["network.proxy.socks_port"]      = int(port_str)
    prefs["network.proxy.socks_version"]   = 4 if server.lower().startswith("socks4://") else 5
    prefs["network.proxy.socks_username"]  = proxy.get("username") or ""
    prefs["network.proxy.socks_password"]  = proxy.get("password") or ""
    prefs["network.proxy.socks_remote_dns"] = True
    return None


def resolve_proxy_timezone(
    proxy: Optional[Dict[str, str]],
    *,
    timeout: float = 6.0,
    endpoint: str = _DEFAULT_TIMEZONE_ENDPOINT,
) -> str:
    """Return the IANA timezone observed from the proxy egress IP.

    ``timezone="auto"`` in the launcher calls this before Firefox starts so
    Playwright's ``timezone_id`` and the process ``TZ`` env can be aligned with
    the proxy. The HTTP request is routed through the same proxy URL the caller
    provided. SOCKS proxies require the package's ``requests[socks]`` dependency.
    """
    if not proxy:
        raise ValueError("timezone='auto' requires a proxy")

    server = (proxy.get("server") or "").strip()
    if not server or server.lower() == "direct://":
        raise ValueError("timezone='auto' requires a non-direct proxy")

    proxies = _requests_proxies(proxy)
    try:
        response = requests.get(endpoint, proxies=proxies, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.InvalidSchema as exc:
        raise RuntimeError(
            "timezone='auto' with SOCKS proxies requires the PySocks extra; "
            "install invisible-playwright with requests[socks] support"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"failed to resolve proxy timezone: {exc}") from exc

    timezone = response.text.strip()
    if not _looks_like_iana_timezone(timezone):
        raise RuntimeError(f"proxy timezone endpoint returned invalid timezone: {timezone!r}")
    return timezone


def _is_socks_scheme(server: str) -> bool:
    return server.lower().startswith(_SOCKS_SCHEMES)


def _strip_scheme(server: str) -> str:
    return server.split("://", 1)[1] if "://" in server else server


def _requests_proxies(proxy: Dict[str, str]) -> Dict[str, str]:
    server = (proxy.get("server") or "").strip()
    proxy_url = _proxy_url_with_auth(
        server,
        proxy.get("username") or "",
        proxy.get("password") or "",
    )
    return {"http": proxy_url, "https": proxy_url}


def _proxy_url_with_auth(server: str, username: str, password: str) -> str:
    if not username and not password:
        return server

    from urllib.parse import quote, urlsplit, urlunsplit

    parts = urlsplit(server)
    if not parts.scheme or not parts.netloc:
        return server

    credentials = quote(username, safe="")
    if password:
        credentials += ":" + quote(password, safe="")
    return urlunsplit((
        parts.scheme,
        f"{credentials}@{parts.netloc}",
        parts.path,
        parts.query,
        parts.fragment,
    ))


def _looks_like_iana_timezone(value: str) -> bool:
    if not value or "/" not in value:
        return False
    return all(part and ".." not in part for part in value.split("/"))
