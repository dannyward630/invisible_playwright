"""Unit tests for `invisible_playwright._proxy.configure_proxy`.

Decision-table coverage of every input partition: None/empty/direct,
SOCKS4/5/default, HTTP/HTTPS, case variants, malformed, mutation contract.
"""
import pytest
import requests

from invisible_playwright._proxy import (
    configure_proxy,
    resolve_proxy_timezone,
    _proxy_url_with_auth,
)


# ──────────────────────────────────────────────────────────────────────
#  CP1-CP7: no-op cases — return None, do NOT mutate prefs
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp1_none_proxy_returns_none():
    prefs = {}
    assert configure_proxy(None, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp2_empty_dict_returns_none():
    prefs = {}
    assert configure_proxy({}, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp3_empty_server_returns_none():
    prefs = {}
    assert configure_proxy({"server": ""}, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp4_whitespace_server_returns_none():
    prefs = {}
    assert configure_proxy({"server": "  "}, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp5_direct_scheme_returns_none():
    prefs = {}
    assert configure_proxy({"server": "direct://"}, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp6_direct_scheme_uppercase_returns_none():
    prefs = {}
    assert configure_proxy({"server": "DIRECT://"}, prefs) is None
    assert prefs == {}


@pytest.mark.unit
def test_cp7_direct_scheme_mixed_case_returns_none():
    prefs = {}
    assert configure_proxy({"server": "DiReCt://"}, prefs) is None
    assert prefs == {}


# ──────────────────────────────────────────────────────────────────────
#  CP8-CP9: HTTP/HTTPS — passthrough (return proxy unchanged, no mutation)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp8_http_proxy_passthrough():
    prefs = {}
    proxy = {"server": "http://proxy:8080"}
    result = configure_proxy(proxy, prefs)
    assert result == proxy
    # No SOCKS-related mutations.
    assert "network.proxy.type" not in prefs
    assert "network.proxy.socks" not in prefs


@pytest.mark.unit
def test_cp9_https_proxy_passthrough():
    prefs = {}
    proxy = {"server": "https://proxy:8080"}
    result = configure_proxy(proxy, prefs)
    assert result == proxy
    assert "network.proxy.type" not in prefs


@pytest.mark.unit
def test_cp8b_http_with_username_password_passthrough():
    """HTTP proxies preserve username/password for Playwright to consume."""
    prefs = {}
    proxy = {"server": "http://proxy:8080", "username": "user", "password": "pw"}
    result = configure_proxy(proxy, prefs)
    assert result == proxy
    assert "network.proxy.type" not in prefs


# ──────────────────────────────────────────────────────────────────────
#  CP10-CP13: SOCKS — mutate prefs, return None
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp10_socks5_with_credentials():
    prefs = {}
    proxy = {
        "server": "socks5://host:1080",
        "username": "u",
        "password": "p",
    }
    result = configure_proxy(proxy, prefs)
    assert result is None
    assert prefs["network.proxy.type"] == 1
    assert prefs["network.proxy.socks"] == "host"
    assert prefs["network.proxy.socks_port"] == 1080
    assert prefs["network.proxy.socks_version"] == 5
    assert prefs["network.proxy.socks_username"] == "u"
    assert prefs["network.proxy.socks_password"] == "p"
    assert prefs["network.proxy.socks_remote_dns"] is True


@pytest.mark.unit
def test_cp11_socks4_sets_version_4():
    prefs = {}
    configure_proxy({"server": "socks4://host:1080"}, prefs)
    assert prefs["network.proxy.socks_version"] == 4


@pytest.mark.unit
def test_cp12_bare_socks_defaults_to_v5():
    prefs = {}
    configure_proxy({"server": "socks://host:1080"}, prefs)
    assert prefs["network.proxy.socks_version"] == 5


@pytest.mark.unit
def test_cp13_socks_scheme_is_case_insensitive():
    prefs = {}
    proxy = {"server": "SOCKS5://HOST:1080"}
    result = configure_proxy(proxy, prefs)
    assert result is None
    assert prefs["network.proxy.type"] == 1
    # Host preserves case (only the scheme is case-folded).
    assert prefs["network.proxy.socks"] == "HOST"
    assert prefs["network.proxy.socks_version"] == 5


# ──────────────────────────────────────────────────────────────────────
#  CP14-CP15: edge SOCKS inputs
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp14_socks_without_port_dropped_silently():
    prefs = {}
    result = configure_proxy({"server": "socks5://hostonly"}, prefs)
    assert result is None
    # Malformed input drops silently — no mutations.
    assert "network.proxy.type" not in prefs
    assert "network.proxy.socks" not in prefs


@pytest.mark.unit
def test_cp15_socks_without_credentials_uses_empty_strings():
    prefs = {}
    configure_proxy({"server": "socks5://host:1080"}, prefs)
    assert prefs["network.proxy.socks_username"] == ""
    assert prefs["network.proxy.socks_password"] == ""


@pytest.mark.unit
def test_cp15b_socks_with_none_credentials_uses_empty_strings():
    """`proxy.get("username")` returning None should resolve to ""."""
    prefs = {}
    configure_proxy(
        {"server": "socks5://host:1080", "username": None, "password": None},
        prefs,
    )
    assert prefs["network.proxy.socks_username"] == ""
    assert prefs["network.proxy.socks_password"] == ""


# ──────────────────────────────────────────────────────────────────────
#  CP16: mutation contract — prefs dict mutated in-place
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp16_prefs_mutated_in_place():
    """Caller's prefs dict receives the SOCKS keys directly (not a copy)."""
    prefs = {"existing.pref": "kept"}
    sentinel = prefs
    configure_proxy({"server": "socks5://host:1080"}, prefs)
    # Same object identity — mutated, not replaced.
    assert prefs is sentinel
    # Existing pref preserved.
    assert prefs["existing.pref"] == "kept"
    # SOCKS keys added.
    assert "network.proxy.type" in prefs
    assert "network.proxy.socks" in prefs


# ──────────────────────────────────────────────────────────────────────
#  CP17: boundary — IPv6-style host preserved via rsplit
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cp17_ipv6_bracketed_host_preserved_via_rsplit():
    """rsplit(':', 1) keeps brackets intact for `[::1]:1080`-style hosts."""
    prefs = {}
    configure_proxy({"server": "socks5://[::1]:1080"}, prefs)
    assert prefs["network.proxy.socks"] == "[::1]"
    assert prefs["network.proxy.socks_port"] == 1080


# ──────────────────────────────────────────────────────────────────────
#  Recheck additions — branches discovered while re-reading _proxy.py
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_socks_with_surrounding_whitespace_in_server_stripped():
    """The implementation strips whitespace before scheme checks."""
    prefs = {}
    result = configure_proxy({"server": "  socks5://host:1080  "}, prefs)
    assert result is None
    assert prefs["network.proxy.socks"] == "host"
    assert prefs["network.proxy.socks_port"] == 1080


@pytest.mark.unit
def test_server_key_missing_returns_none():
    """No 'server' key → treated as empty → no-op."""
    prefs = {}
    result = configure_proxy({"username": "u"}, prefs)
    assert result is None
    assert prefs == {}


@pytest.mark.unit
def test_server_key_none_returns_none():
    """`server: None` is normalized to "" by the implementation."""
    prefs = {}
    result = configure_proxy({"server": None}, prefs)
    assert result is None
    assert prefs == {}


@pytest.mark.unit
def test_socks_port_coerced_to_int():
    """Port string is parsed via int() — not a numeric string."""
    prefs = {}
    configure_proxy({"server": "socks5://host:443"}, prefs)
    assert prefs["network.proxy.socks_port"] == 443
    assert isinstance(prefs["network.proxy.socks_port"], int)


# ──────────────────────────────────────────────────────────────────────
#  Proxy timezone auto-resolution
# ──────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text="Europe/Vienna") -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


@pytest.mark.unit
def test_proxy_url_with_auth_percent_encodes_credentials():
    out = _proxy_url_with_auth("socks5://host:1080", "user@example.com", "p/a:ss")
    assert out == "socks5://user%40example.com:p%2Fa%3Ass@host:1080"


@pytest.mark.unit
def test_proxy_url_without_auth_returns_server_unchanged():
    assert _proxy_url_with_auth("socks5://host:1080", "", "") == "socks5://host:1080"


@pytest.mark.unit
def test_resolve_proxy_timezone_routes_request_through_proxy(monkeypatch):
    calls = []

    def fake_get(url, *, proxies, timeout):
        calls.append((url, proxies, timeout))
        return _FakeResponse("Europe/Vienna\n")

    monkeypatch.setattr("invisible_playwright._proxy.requests.get", fake_get)

    timezone = resolve_proxy_timezone(
        {"server": "socks5://host:1080", "username": "u", "password": "p"},
        timeout=1.5,
        endpoint="https://example.test/timezone",
    )

    assert timezone == "Europe/Vienna"
    assert calls == [(
        "https://example.test/timezone",
        {
            "http": "socks5://u:p@host:1080",
            "https": "socks5://u:p@host:1080",
        },
        1.5,
    )]


@pytest.mark.unit
def test_resolve_proxy_timezone_rejects_missing_proxy():
    with pytest.raises(ValueError, match="requires a proxy"):
        resolve_proxy_timezone(None)


@pytest.mark.unit
def test_resolve_proxy_timezone_rejects_direct_proxy():
    with pytest.raises(ValueError, match="non-direct proxy"):
        resolve_proxy_timezone({"server": "direct://"})


@pytest.mark.unit
def test_resolve_proxy_timezone_rejects_invalid_timezone(monkeypatch):
    monkeypatch.setattr(
        "invisible_playwright._proxy.requests.get",
        lambda *args, **kwargs: _FakeResponse("not-a-zone"),
    )
    with pytest.raises(RuntimeError, match="invalid timezone"):
        resolve_proxy_timezone({"server": "http://host:8080"})


@pytest.mark.unit
def test_resolve_proxy_timezone_wraps_request_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.RequestException("network down")

    monkeypatch.setattr("invisible_playwright._proxy.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="failed to resolve proxy timezone"):
        resolve_proxy_timezone({"server": "http://host:8080"})


@pytest.mark.unit
def test_socks_non_numeric_port_raises_value_error():
    """Non-numeric port is a programmer error — int() raises."""
    prefs = {}
    with pytest.raises(ValueError):
        configure_proxy({"server": "socks5://host:notaport"}, prefs)
