"""Public helpers for building Firefox launch config without using ``InvisiblePlaywright``.

Use these when you need to call ``playwright.firefox.launch()`` (or
``firefox.launch_persistent_context()``) directly with our patched binary
and stealth prefs, instead of using the ``InvisiblePlaywright`` context
manager.

Typical caller is an external integration that owns its own browser
lifecycle (a Crawlee/Skyvern/changedetection-style fetcher, a Playwright
Server wrapper, a multi-language harness) and just wants the building
blocks::

    from playwright.async_api import async_playwright
    from invisible_playwright import ensure_binary, get_default_stealth_prefs

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=str(ensure_binary()),
            firefox_user_prefs=get_default_stealth_prefs(seed=42),
        )

For everyday Python usage the ``InvisiblePlaywright`` context manager is
still the recommended entry point; these helpers expose the same internals
without the lifecycle ownership.

.. note::
   When calling ``firefox.launch()`` yourself, pass ``headless=False`` and
   manage the display hiding (Xvfb on Linux, hidden desktop on Windows)
   externally. Passing ``headless=True`` directly to Playwright puts
   Firefox in true headless mode, which skips the real rendering pipeline
   and breaks canvas / audio / WebGL fingerprint coherence. The
   ``InvisiblePlaywright`` context manager does this translation
   automatically; the public helpers leave it to the caller.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ._fpforge import generate_profile
from ._webgl_personas import forced_gpu_class
from ._geo import resolve_session_locale
from ._headless import cloak_prefs
from ._proxy import configure_proxy
from .constants import BINARY_VERSION, PLAYWRIGHT_DRIVER_VERSION
from .download import ensure_binary
from .launcher import _CHROME_H, _CHROME_W, _TASKBAR_H, _tz_env
from .prefs import translate_profile_to_prefs


def get_default_stealth_prefs(
    seed: Optional[int] = None,
    *,
    pin: Optional[Dict[str, Any]] = None,
    locale: str = "en-US",
    timezone: str = "",
    extra_prefs: Optional[Dict[str, Any]] = None,
    humanize: Union[bool, float] = True,
    virtual_display: bool = False,
) -> Dict[str, Any]:
    """Build a complete ``firefox_user_prefs`` dict for ``firefox.launch()``.

    Same prefs that ``InvisiblePlaywright(seed=..., locale=..., timezone=...,
    extra_prefs=..., humanize=...)`` would inject. Use this when you need to
    drive ``playwright.firefox.launch()`` yourself.

    Args:
        seed: Integer seed for the Bayesian fingerprint sampler. Same seed
            produces the same fingerprint. ``None`` generates a fresh
            random int31 (matches ``InvisiblePlaywright`` default).
        pin: Optional dict forcing specific fingerprint fields while the
            rest stays seed-derived. See ``docs/pinning.md``.
        locale: BCP-47 tag (e.g. ``"en-US"``). Drives ``Accept-Language``
            and ``navigator.language``. Use ``"auto"`` with a concrete
            ``timezone`` to derive a common regional locale.
        timezone: IANA timezone (e.g. ``"America/New_York"``). Empty means
            use the host TZ. This pure pref builder does NOT resolve
            ``"auto"`` (that needs the proxy + a network lookup at launch
            time) — pass a concrete zone here, or use ``InvisiblePlaywright``
            / ``resolve_session_timezone(timezone, proxy)`` for ``"auto"``.
        extra_prefs: Optional dict overlaid LAST onto the generated prefs.
        humanize: When True (default), every mouse move is expanded into
            a Bezier trajectory by the patched Juggler. A float caps the
            motion in seconds. False disables the behavior.
        virtual_display: When True on Windows, apply GPU-disabling prefs
            to prevent GPU process crashes on virtual desktops without
            D3D11 backend.

    Returns:
        Dict ready to pass as ``firefox_user_prefs=`` to
        ``playwright.firefox.launch()`` or ``launch_persistent_context()``.
    """
    resolved_seed = int(seed) if seed is not None else secrets.randbits(31)
    resolved_locale = resolve_session_locale(locale, timezone)
    profile = generate_profile(resolved_seed, pin=pin, fixed_gpu_class=forced_gpu_class(resolved_seed))
    prefs = translate_profile_to_prefs(
        profile,
        locale=resolved_locale,
        timezone=timezone,
        extra_prefs=extra_prefs,
        virtual_display=virtual_display,
    )
    # stealthfox.* is the namespace the binary's Juggler reads (see launcher.py note).
    prefs["stealthfox.humanize"] = bool(humanize)
    if humanize:
        max_seconds = float(humanize) if not isinstance(humanize, bool) else 1.5
        prefs["stealthfox.humanize.maxTime"] = str(max_seconds)
    return prefs


def get_default_args() -> List[str]:
    """Return the default Firefox CLI args to pass via ``args=``.

    Currently empty list, since all our stealth configuration is delivered
    via ``firefox_user_prefs`` rather than CLI flags. Exposed for parity
    with the ``cloakbrowser.config.get_default_stealth_args`` pattern and
    to future-proof integrations that already wire ``args=[*existing,
    *get_default_args()]``.
    """
    return []


def _context_options_for_profile(profile: Any, *, locale: str, timezone: str) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "viewport": {
            "width": profile.screen.width - _CHROME_W,
            "height": profile.screen.height - _TASKBAR_H - _CHROME_H,
        },
        "screen": {"width": profile.screen.width, "height": profile.screen.height},
        "deviceScaleFactor": profile.screen.dpr,
        "colorScheme": "dark" if profile.dark_theme else "light",
    }
    if locale:
        options["locale"] = locale
    if timezone:
        options["timezoneId"] = timezone
    return options


def build_playwright_launch_config(
    seed: Optional[int] = None,
    *,
    pin: Optional[Dict[str, Any]] = None,
    locale: str = "en-US",
    timezone: str = "",
    extra_prefs: Optional[Dict[str, Any]] = None,
    humanize: Union[bool, float] = True,
    headless: bool = False,
    proxy: Optional[Dict[str, str]] = None,
    extra_args: Optional[List[str]] = None,
    binary_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Build a JSON-serializable Playwright config for non-Python callers.

    This is the bridge for TypeScript/JavaScript integrations: callers can use
    the Python sampler once, then pass the returned ``launchOptions`` to
    ``firefox.launch()`` and ``contextOptions`` to ``browser.newContext()``.
    ``locale="auto"`` derives a common regional locale from the given
    ``timezone``. ``headless=True`` follows the wrapper contract: Firefox still
    launches in headed mode so the rendering pipeline stays realistic. On
    Linux the caller must provide a virtual display such as ``xvfb-run``; on
    Windows/macOS the patched binary can cloak the headed window.
    """
    resolved_seed = int(seed) if seed is not None else secrets.randbits(31)
    resolved_locale = resolve_session_locale(locale, timezone)
    profile = generate_profile(
        resolved_seed, pin=pin, fixed_gpu_class=forced_gpu_class(resolved_seed)
    )
    prefs = translate_profile_to_prefs(
        profile,
        locale=resolved_locale,
        timezone=timezone,
        extra_prefs=extra_prefs,
        virtual_display=bool(headless and sys.platform == "win32"),
    )
    if headless and sys.platform in ("win32", "darwin"):
        for key, value in cloak_prefs().items():
            prefs.setdefault(key, value)
    prefs["stealthfox.humanize"] = bool(humanize)
    if humanize:
        prefs["stealthfox.humanize.maxTime"] = (
            str(1.5) if isinstance(humanize, bool) else str(float(humanize))
        )

    playwright_proxy = configure_proxy(proxy, prefs)
    executable = Path(binary_path) if binary_path is not None else ensure_binary()
    launch_options: Dict[str, Any] = {
        "executablePath": str(executable),
        "headless": False,
        "firefoxUserPrefs": prefs,
    }
    args = list(extra_args or get_default_args())
    if args:
        launch_options["args"] = args
    if playwright_proxy:
        launch_options["proxy"] = playwright_proxy
    env: Dict[str, str] = {}
    if timezone:
        env["TZ"] = _tz_env(timezone)
    if env:
        launch_options["env"] = env

    return {
        "seed": resolved_seed,
        "binaryVersion": BINARY_VERSION,
        "playwrightVersion": PLAYWRIGHT_DRIVER_VERSION,
        "launchOptions": launch_options,
        "contextOptions": _context_options_for_profile(
            profile, locale=resolved_locale, timezone=timezone
        ),
        "requiresVirtualDisplay": bool(headless and sys.platform == "linux"),
    }
