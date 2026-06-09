"""Fingerprint surface tests — replicate the checks performed by the canonical
anti-bot detection libraries against an OFFLINE browser session.

Each test asserts the SAME thing the upstream detector would flag. A pass
here means our patched build appears human to that detector; a fail
means a real stealth hole that anti-bot kits would exploit in production.

Detector libraries studied (all FOSS, MIT-licensed):
  - github.com/fingerprintjs/BotD            — 19 detectors, the most
                                                widely deployed client-side
                                                bot detector
  - github.com/abrahamjuliot/creepjs         — headless / stealth / lies
                                                modules
  - github.com/fingerprintjs/fingerprintjs   — canvas / audio / color /
                                                touch consistency
  - github.com/antoinevastel/fpscanner       — UA / platform / oscpu
                                                cross-checks
  - bot.sannysoft.com                        — classic Puppeteer harness

Everything runs against `about:blank` with NO network and NO proxy. The
suite is intended to be part of the release-gate: pre-push hook runs
`pytest -m e2e` and these tests must be green on every release.

Run only this file:
    pytest tests/test_fingerprint_surface.py -m e2e -v
"""
from __future__ import annotations

import re

import pytest

from invisible_playwright import InvisiblePlaywright


# ────────────────────────────────────────────────────────────────────
# Inline PIN — a coherent mid-range Windows desktop. Not user-config:
# these specific values are what the surface tests assert against.
# Keep PIN small (only fields that JS exposes) and stable across runs.
# ────────────────────────────────────────────────────────────────────

PIN = {
    "screen.width": 1920,
    "screen.height": 1080,
    "screen.avail_width": 1920,
    "screen.avail_height": 1040,
    "screen.dpr": 1.0,
    "hardware.concurrency": 8,
    "audio.sample_rate": 48000,
    "audio.max_channel_count": 2,
}


@pytest.fixture(scope="module")
def page(firefox_binary):
    """One headless browser shared across the whole module.
    ~20s startup paid once, then every test runs in ~50ms."""
    with InvisiblePlaywright(
        seed=42,
        pin=PIN,
        binary_path=firefox_binary,
        headless=True,
    ) as browser:
        ctx = browser.new_context()
        p = ctx.new_page()
        p.goto("about:blank", timeout=30_000)
        yield p


def _ev(page, expr):
    return page.evaluate(expr)


# ===========================================================================
# sannysoft.com — classic Puppeteer detection harness
# ===========================================================================


@pytest.mark.e2e
def test_sannysoft_chrome_object_consistency(page):
    """Firefox UA + window.chrome present = bot-framework leak."""
    if "Firefox" in _ev(page, "navigator.userAgent"):
        assert not _ev(page, "typeof window.chrome !== 'undefined'")


@pytest.mark.e2e
def test_sannysoft_permissions_query_works(page):
    """navigator.permissions.query() must return a proper PermissionStatus."""
    ok = _ev(page, """async () => {
        if (!navigator.permissions || !navigator.permissions.query) return false;
        try {
            const r = await navigator.permissions.query({name: 'notifications'});
            return r && typeof r.state === 'string';
        } catch (e) { return false; }
    }""")
    assert ok


@pytest.mark.e2e
def test_sannysoft_iframe_chrome_not_leaked(page):
    """iframe.contentWindow.chrome must not leak on Firefox UA."""
    if "Firefox" not in _ev(page, "navigator.userAgent"):
        pytest.skip("Firefox-only invariant")
    leaks = _ev(page, """() => {
        const iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        document.body.appendChild(iframe);
        const is = typeof iframe.contentWindow.chrome !== 'undefined';
        document.body.removeChild(iframe);
        return is;
    }""")
    assert not leaks


@pytest.mark.e2e
def test_sannysoft_iframe_languages_not_empty(page):
    """Iframe-scope navigator.languages must have ≥1 entry."""
    n = _ev(page, """() => {
        const f = document.createElement('iframe');
        f.style.display = 'none';
        document.body.appendChild(f);
        const len = f.contentWindow.navigator.languages.length;
        document.body.removeChild(f);
        return len;
    }""")
    assert n > 0


# ===========================================================================
# FingerprintJS — fingerprint surface coherence
# ===========================================================================


@pytest.mark.e2e
def test_fpjs_canvas_2d_context_returns_valid(page):
    ok = _ev(page, """() => {
        const c = document.createElement('canvas');
        c.width = 100; c.height = 100;
        const ctx = c.getContext('2d');
        if (!ctx) return false;
        ctx.fillText('test', 10, 10);
        const data = c.toDataURL();
        return data.length > 100 && data.startsWith('data:image/png;base64');
    }""")
    assert ok


@pytest.mark.e2e
def test_fpjs_audio_context_works(page):
    ok = _ev(page, """async () => {
        try {
            const ctx = new (window.OfflineAudioContext ||
                              window.webkitOfflineAudioContext)(1, 5000, 44100);
            const osc = ctx.createOscillator();
            osc.connect(ctx.destination);
            osc.start(0);
            const buf = await ctx.startRendering();
            return buf && buf.length > 0;
        } catch (e) { return false; }
    }""")
    assert ok


@pytest.mark.e2e
def test_fpjs_color_gamut_query_works(page):
    """matchMedia('(color-gamut: ...)') must match at least srgb."""
    ok = _ev(page, """matchMedia('(color-gamut: srgb)').matches ||
                      matchMedia('(color-gamut: p3)').matches ||
                      matchMedia('(color-gamut: rec2020)').matches""")
    assert ok


@pytest.mark.e2e
def test_fpjs_screen_color_depth_realistic(page):
    """Atypical color depths are headless-distinctive."""
    cd = _ev(page, "screen.colorDepth")
    assert cd in (24, 30, 32)


# ===========================================================================
# PIN-locked surfaces (the values declared in PIN above)
# ===========================================================================


@pytest.mark.e2e
def test_pin_screen_width_lands_in_screen_object(page):
    assert _ev(page, "screen.width") == PIN["screen.width"]


@pytest.mark.e2e
def test_pin_screen_height_lands_in_screen_object(page):
    assert _ev(page, "screen.height") == PIN["screen.height"]


@pytest.mark.e2e
def test_pin_hardware_concurrency_lands_in_navigator(page):
    assert (_ev(page, "navigator.hardwareConcurrency")
            == PIN["hardware.concurrency"])


@pytest.mark.e2e
def test_pin_audio_sample_rate_lands_in_AudioContext(page):
    assert _ev(page,
        "(new (window.AudioContext||window.webkitAudioContext)()).sampleRate"
    ) == PIN["audio.sample_rate"]


@pytest.mark.e2e
def test_pin_audio_max_channels_lands_in_destination(page):
    assert _ev(page,
        "(new (window.AudioContext||window.webkitAudioContext)())"
        ".destination.maxChannelCount"
    ) == PIN["audio.max_channel_count"]


# ===========================================================================
# fpscanner-style cross-checks
# ===========================================================================


@pytest.mark.e2e
def test_fpscanner_ua_vs_platform_consistent(page):
    """UA OS substring must agree with navigator.platform OS substring."""
    ua = _ev(page, "navigator.userAgent")
    platform = _ev(page, "navigator.platform")
    if "Windows" in ua:
        assert "Win" in platform, f"UA Win but platform={platform!r}"
    elif "Mac" in ua:
        assert "Mac" in platform
    elif "Linux" in ua:
        assert "Linux" in platform or "X11" in platform


@pytest.mark.e2e
def test_fpscanner_no_userAgentData_on_firefox(page):
    """navigator.userAgentData is Chromium-only. Presence on Firefox UA = bot."""
    if "Firefox" in _ev(page, "navigator.userAgent"):
        assert not _ev(page, "'userAgentData' in navigator")
