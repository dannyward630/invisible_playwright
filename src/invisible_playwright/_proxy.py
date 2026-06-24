"""Proxy translation shared by sync and async launchers.

SOCKS proxies are driven entirely by the patched Firefox prefs (the
``nsProtocolProxyService`` patch reads ``network.proxy.socks_username``
and ``socks_password``). HTTP/HTTPS proxies go through Playwright's own
``proxy=`` kwarg so it can negotiate Basic auth.
"""
from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional
from urllib.parse import urlsplit


_SOCKS_SCHEMES = {"socks5", "socks4", "socks"}
_PLAYWRIGHT_PROXY_SCHEMES = {"http", "https"}
_PROXY_SCHEMES = _SOCKS_SCHEMES | _PLAYWRIGHT_PROXY_SCHEMES | {"direct"}


class ProxyConfigError(ValueError):
    """Raised when a proxy server URL cannot be used safely."""


class ParsedProxy(NamedTuple):
    scheme: str
    server: str
    host: str
    port: int

    @property
    def is_socks(self) -> bool:
        return self.scheme in _SOCKS_SCHEMES

    @property
    def is_playwright_proxy(self) -> bool:
        return self.scheme in _PLAYWRIGHT_PROXY_SCHEMES


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
    parsed = parse_proxy(proxy)
    if parsed is None:
        return None

    if parsed.is_playwright_proxy:
        return proxy

    prefs["network.proxy.type"]            = 1
    prefs["network.proxy.socks"]           = parsed.host
    prefs["network.proxy.socks_port"]      = parsed.port
    prefs["network.proxy.socks_version"]   = 4 if parsed.scheme == "socks4" else 5
    prefs["network.proxy.socks_username"]  = proxy.get("username") or ""
    prefs["network.proxy.socks_password"]  = proxy.get("password") or ""
    prefs["network.proxy.socks_remote_dns"] = True
    return None


def proxy_is_set(proxy: Optional[Dict[str, str]]) -> bool:
    """Return whether ``proxy`` contains a usable non-direct proxy URL."""
    return parse_proxy(proxy) is not None


def parse_proxy(proxy: Optional[Dict[str, str]]) -> Optional[ParsedProxy]:
    """Validate and parse the public proxy dict.

    ``None``, empty, blank ``server``, and ``direct://`` mean "no proxy".
    Real proxy servers must include an explicit scheme and port so browser
    launch, egress lookup, and diagnostics cannot disagree about routing.
    """
    if not proxy:
        return None

    server = (proxy.get("server") or "").strip()
    if not server:
        return None
    if "://" not in server:
        raise ProxyConfigError(
            "proxy server must include a scheme, e.g. socks5://host:1080"
        )

    split = urlsplit(server)
    scheme = split.scheme.lower()
    if scheme == "direct" and server.lower() == "direct://":
        return None
    if scheme not in _PROXY_SCHEMES:
        raise ProxyConfigError(
            "proxy server scheme must be one of direct, socks5, socks4, "
            "socks, http, or https"
        )
    if scheme == "direct":
        raise ProxyConfigError('direct proxy must be exactly "direct://"')
    if split.username is not None or split.password is not None:
        raise ProxyConfigError(
            "proxy credentials must be passed as username/password fields, "
            "not embedded in the server URL"
        )
    if split.path not in ("", "/") or split.query or split.fragment:
        raise ProxyConfigError(
            "proxy server URL must not include a path, query, or fragment"
        )
    if not split.netloc:
        raise ProxyConfigError("proxy server must include a host")

    try:
        port = split.port
    except ValueError as exc:
        raise ProxyConfigError(f"proxy server has an invalid port: {exc}") from exc
    if port is None:
        raise ProxyConfigError("proxy server must include a port")

    host = split.netloc.rsplit(":", 1)[0]
    if not host:
        raise ProxyConfigError("proxy server must include a host")
    return ParsedProxy(scheme=scheme, server=server, host=host, port=port)
