"""Unit tests for the public ``config`` helpers."""

import pytest

from invisible_playwright import (
    build_playwright_launch_config,
    ensure_binary,
    get_default_args,
    get_default_stealth_prefs,
)
from invisible_playwright.config import get_default_stealth_prefs as _direct


pytestmark = pytest.mark.unit


def test_get_default_args_is_empty_list():
    """Currently no baseline CLI args, but must return a list (mutable, fresh each call)."""
    args = get_default_args()
    assert args == []
    assert isinstance(args, list)
    args.append("--foo")
    # next call must return a fresh empty list, not the mutated one
    assert get_default_args() == []


def test_get_default_stealth_prefs_random_seed_returns_dict():
    """No seed -> fresh random fingerprint, dict has expected stealth keys."""
    prefs = get_default_stealth_prefs()
    assert isinstance(prefs, dict)
    assert len(prefs) > 0
    # humanize toggle is always set explicitly
    assert "stealthfox.humanize" in prefs
    assert prefs["stealthfox.humanize"] is True


def test_get_default_stealth_prefs_seed_is_deterministic():
    """Same seed -> byte-identical prefs across calls."""
    a = get_default_stealth_prefs(seed=42)
    b = get_default_stealth_prefs(seed=42)
    assert a == b


def test_get_default_stealth_prefs_different_seeds_differ():
    """Different seeds -> different prefs."""
    a = get_default_stealth_prefs(seed=1)
    b = get_default_stealth_prefs(seed=2)
    assert a != b


def test_humanize_false_disables_prefs():
    """humanize=False removes the maxTime knob and flips the toggle to False."""
    prefs = get_default_stealth_prefs(seed=42, humanize=False)
    assert prefs["stealthfox.humanize"] is False
    assert "stealthfox.humanize.maxTime" not in prefs


def test_humanize_default_sets_max_time_1_5():
    """humanize=True -> default maxTime is 1.5s, stored as string."""
    prefs = get_default_stealth_prefs(seed=42, humanize=True)
    assert prefs["stealthfox.humanize"] is True
    assert prefs["stealthfox.humanize.maxTime"] == "1.5"


def test_humanize_float_overrides_max_time():
    """Float for humanize is the explicit cap in seconds."""
    prefs = get_default_stealth_prefs(seed=42, humanize=3.0)
    assert prefs["stealthfox.humanize"] is True
    assert prefs["stealthfox.humanize.maxTime"] == "3.0"


def test_extra_prefs_overlay_takes_precedence():
    """extra_prefs overlay LAST overrides any baseline value."""
    prefs = get_default_stealth_prefs(
        seed=42, extra_prefs={"some.custom.pref": 999}
    )
    assert prefs["some.custom.pref"] == 999


def test_extra_prefs_can_override_baseline():
    """A key in extra_prefs that also exists in baseline gets overridden."""
    baseline = get_default_stealth_prefs(seed=42)
    a_baseline_key = next(iter(baseline.keys()))
    overridden = get_default_stealth_prefs(
        seed=42, extra_prefs={a_baseline_key: "OVERRIDDEN_SENTINEL"}
    )
    assert overridden[a_baseline_key] == "OVERRIDDEN_SENTINEL"


def test_locale_argument_changes_prefs():
    """Different locales produce different prefs (Accept-Language affected)."""
    en = get_default_stealth_prefs(seed=42, locale="en-US")
    it = get_default_stealth_prefs(seed=42, locale="it-IT")
    assert en != it


def test_timezone_argument_changes_prefs():
    """Different timezones produce different prefs."""
    ny = get_default_stealth_prefs(seed=42, timezone="America/New_York")
    rome = get_default_stealth_prefs(seed=42, timezone="Europe/Rome")
    assert ny != rome


def test_get_default_stealth_prefs_rejects_auto_timezone():
    """Pure pref generation cannot resolve proxy/egress-dependent auto TZ."""
    with pytest.raises(ValueError, match='timezone="auto"'):
        get_default_stealth_prefs(seed=42, timezone="auto")


def test_pin_argument_forces_specific_fields():
    """Pin forces a specific field while the rest stays seed-derived."""
    plain = get_default_stealth_prefs(seed=42)
    pinned = get_default_stealth_prefs(
        seed=42, pin={"hardware.concurrency": 999}
    )
    # something in the dict must differ vs the plain seed=42 build
    assert plain != pinned


def test_public_import_matches_direct_import():
    """Top-level re-export and direct module import return identical output."""
    a = get_default_stealth_prefs(seed=42)
    b = _direct(seed=42)
    assert a == b


def test_ensure_binary_is_callable_via_public_namespace():
    """ensure_binary is re-exported and stays callable from the package root."""
    # We don't invoke it (would trigger a network download in CI) — just
    # verify the public attribute is the same callable as the underlying.
    from invisible_playwright.download import ensure_binary as _direct_eb
    assert ensure_binary is _direct_eb


def test_build_playwright_launch_config_is_deterministic(tmp_path):
    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    a = build_playwright_launch_config(
        seed=42,
        locale="de-DE",
        timezone="Europe/Berlin",
        binary_path=fake_binary,
    )
    b = build_playwright_launch_config(
        seed=42,
        locale="de-DE",
        timezone="Europe/Berlin",
        binary_path=fake_binary,
    )

    assert a == b
    assert a["seed"] == 42
    assert a["playwrightVersion"]
    assert a["launchOptions"]["executablePath"] == str(fake_binary)
    assert a["launchOptions"]["headless"] is False
    assert a["launchOptions"]["env"]["TZ"] == "Europe/Berlin"
    assert a["contextOptions"]["locale"] == "de-DE"
    assert a["contextOptions"]["timezoneId"] == "Europe/Berlin"
    assert a["contextOptions"]["viewport"]["width"] > 0
    assert a["contextOptions"]["screen"]["width"] > 0
    assert "firefoxUserPrefs" in a["launchOptions"]


def test_build_playwright_launch_config_routes_socks_proxy_to_prefs(tmp_path, monkeypatch):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")
    monkeypatch.setattr(
        "invisible_playwright.config.prepare_session_geo",
        lambda timezone, proxy_arg: SessionGeo("America/New_York", "203.0.113.7"),
    )

    cfg = build_playwright_launch_config(
        seed=42,
        binary_path=fake_binary,
        proxy={
            "server": "socks5://proxy.example:1080",
            "username": "u",
            "password": "p",
        },
    )

    launch = cfg["launchOptions"]
    prefs = launch["firefoxUserPrefs"]
    assert "proxy" not in launch
    assert prefs["network.proxy.socks"] == "proxy.example"
    assert prefs["network.proxy.socks_port"] == 1080
    assert prefs["network.proxy.socks_username"] == "u"
    assert prefs["network.proxy.socks_password"] == "p"


def test_build_playwright_launch_config_keeps_http_proxy_for_playwright(tmp_path, monkeypatch):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")
    proxy = {"server": "http://proxy.example:8080", "username": "u"}
    monkeypatch.setattr(
        "invisible_playwright.config.prepare_session_geo",
        lambda timezone, proxy_arg: SessionGeo("America/New_York", "203.0.113.7"),
    )

    cfg = build_playwright_launch_config(seed=42, binary_path=fake_binary, proxy=proxy)

    assert cfg["launchOptions"]["proxy"] is proxy
    assert "network.proxy.socks" not in cfg["launchOptions"]["firefoxUserPrefs"]


def test_build_playwright_launch_config_resolves_auto_timezone(tmp_path, monkeypatch):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    seen = {}

    def fake_prepare(timezone, proxy):
        seen["timezone"] = timezone
        seen["proxy"] = proxy
        return SessionGeo("Europe/Warsaw", None)

    monkeypatch.setattr("invisible_playwright.config.prepare_session_geo", fake_prepare)

    cfg = build_playwright_launch_config(
        seed=42,
        locale="auto",
        timezone="auto",
        binary_path=fake_binary,
    )

    assert seen == {"timezone": "auto", "proxy": None}
    assert cfg["resolvedTimezone"] == "Europe/Warsaw"
    assert cfg["egressIp"] is None
    assert cfg["launchOptions"]["env"]["TZ"] == "Europe/Warsaw"
    assert cfg["contextOptions"]["timezoneId"] == "Europe/Warsaw"
    assert cfg["contextOptions"]["locale"] == "pl-PL"
    assert cfg["launchOptions"]["firefoxUserPrefs"]["intl.accept_languages"] == "pl-PL, pl"


def test_build_playwright_launch_config_auto_timezone_fallback_omits_auto(tmp_path, monkeypatch):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")
    monkeypatch.setattr(
        "invisible_playwright.config.prepare_session_geo",
        lambda timezone, proxy: SessionGeo("", None),
    )

    cfg = build_playwright_launch_config(
        seed=42,
        timezone="auto",
        binary_path=fake_binary,
    )

    assert cfg["resolvedTimezone"] == ""
    assert "env" not in cfg["launchOptions"]
    assert "timezoneId" not in cfg["contextOptions"]
    assert "juggler.timezone.override" not in cfg["launchOptions"]["firefoxUserPrefs"]


def test_build_playwright_launch_config_proxy_sets_webrtc_egress_env(tmp_path, monkeypatch):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")
    proxy = {"server": "socks5://proxy.example:1080"}

    monkeypatch.setattr(
        "invisible_playwright.config.prepare_session_geo",
        lambda timezone, proxy_arg: SessionGeo("America/New_York", "203.0.113.7"),
    )

    cfg = build_playwright_launch_config(
        seed=42,
        locale="auto",
        proxy=proxy,
        binary_path=fake_binary,
    )

    env = cfg["launchOptions"]["env"]
    assert cfg["resolvedTimezone"] == "America/New_York"
    assert cfg["egressIp"] == "203.0.113.7"
    assert env["TZ"] == "EST5EDT"
    assert env["STEALTHFOX_WEBRTC_PUBLIC_IP"] == "203.0.113.7"
    assert env["STEALTHFOX_WEBRTC_DISABLE_IPV6"] == "1"
    assert cfg["contextOptions"]["locale"] == "en-US"
