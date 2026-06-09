#!/usr/bin/env python3
"""CI drive gate — the firefox-8 catcher.

A raw `firefox --screenshot` proves nothing about automation: a juggler-less
binary renders a screenshot just fine and ships broken (firefox-8 did exactly
that). This DRIVES the binary the way users will — Playwright launches it over
the juggler pipe, loads a real page, and round-trips JS. A binary with a
missing/broken juggler throws TargetClosedError here and the gate fails.

Headless, NO screenshot → GPU-free, so it can't false-fail on GPU-less hosted
runners. Zero proxy / zero secrets → safe in public CI. (The proxy realness
gate — fppro/webrtc — stays local, it needs secrets.)

Usage:  python ci_drive_gate.py /path/to/firefox[.exe | .app/Contents/MacOS/firefox]
Exit 0 + "DRIVE GATE OK ..." on success; non-zero with a reason on failure.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def main(exe: str) -> int:
    with sync_playwright() as p:
        browser = p.firefox.launch(executable_path=exe, headless=True)
        page = browser.new_page()
        # data: URL → real HTML parse + DOM + JS, fully offline (no network/proxy).
        page.goto("data:text/html,<title>dt</title><h1 id=x>hello-drive</h1>")
        ua = page.evaluate("navigator.userAgent")
        webdriver = page.evaluate("navigator.webdriver")
        text = page.evaluate("() => document.getElementById('x').textContent")
        browser.close()

    assert "Firefox" in ua, f"unexpected UA (binary not driving correctly): {ua!r}"
    assert text == "hello-drive", f"DOM/JS roundtrip failed: {text!r}"
    # Free stealth smoke: the patched build hides navigator.webdriver even when
    # driven by bare Playwright. A True here is a stealth regression, not a crash.
    assert not webdriver, f"navigator.webdriver leaked True (stealth regression): {webdriver!r}"

    print(f"DRIVE GATE OK | UA={ua} | webdriver={webdriver} | dom-roundtrip=ok")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: ci_drive_gate.py <path-to-firefox-binary>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
