"""Unit tests for the ``_headless`` virtual-display dispatcher.

The dispatcher (``make_virtual_display``) is the only piece of
``_headless`` we can exercise as a unit test on a single platform:
``_WindowsVirtualDesktop`` actually creates a Win32 desktop on
construction's later ``start()`` call, and ``_LinuxVirtualDisplay`` calls
``Xvfb`` — both belong in integration/E2E coverage. The dispatcher's
job is pure platform routing, which we patch via ``monkeypatch``.

Per scope: Windows-specific + platform-agnostic only. We still cover
the Linux dispatch branch because instantiating ``_LinuxVirtualDisplay``
does no I/O — Xvfb is only spawned in ``start()``, which we never call.
"""
from __future__ import annotations

import pytest

import invisible_playwright._headless as headless
from invisible_playwright._headless import (
    _LinuxVirtualDisplay,
    _WindowsVirtualDesktop,
    make_virtual_display,
)


@pytest.mark.unit
def test_make_virtual_display_returns_windows_desktop_on_win32(monkeypatch):
    monkeypatch.setattr(headless.sys, "platform", "win32")
    vd = make_virtual_display()
    assert isinstance(vd, _WindowsVirtualDesktop)


@pytest.mark.unit
def test_make_virtual_display_returns_linux_xvfb_on_linux(monkeypatch):
    """``__init__`` of ``_LinuxVirtualDisplay`` does no I/O — only ``start()``
    spawns Xvfb. Exercising the dispatcher here is safe on any host."""
    monkeypatch.setattr(headless.sys, "platform", "linux")
    vd = make_virtual_display()
    assert isinstance(vd, _LinuxVirtualDisplay)


@pytest.mark.unit
def test_make_virtual_display_accepts_linux_variants(monkeypatch):
    """``sys.platform`` can be ``linux2`` on older Pythons / WSL builds.
    The dispatcher uses ``startswith("linux")`` to accept all variants."""
    monkeypatch.setattr(headless.sys, "platform", "linux2")
    assert isinstance(make_virtual_display(), _LinuxVirtualDisplay)


@pytest.mark.unit
def test_make_virtual_display_raises_on_darwin(monkeypatch):
    """macOS is unsupported — the dispatcher must raise with a clear
    message rather than returning a no-op shim. ``InvisiblePlaywright``
    relies on this to bail before launching Firefox on a system where
    the patched binary doesn't exist."""
    monkeypatch.setattr(headless.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="Windows and Linux only"):
        make_virtual_display()


@pytest.mark.unit
def test_make_virtual_display_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(headless.sys, "platform", "freebsd14")
    with pytest.raises(RuntimeError, match="Windows and Linux only"):
        make_virtual_display()


@pytest.mark.unit
def test_make_virtual_display_error_mentions_offending_platform(monkeypatch):
    """Error message should include the actual ``sys.platform`` so the
    user can diagnose why their CI / weird container is being rejected."""
    monkeypatch.setattr(headless.sys, "platform", "sunos5")
    with pytest.raises(RuntimeError, match="sunos5"):
        make_virtual_display()


@pytest.mark.unit
def test_windows_desktop_initial_state_is_clean():
    """Construction must not allocate Win32 resources — only ``start()``
    does. Allows users to instantiate ``InvisiblePlaywright`` without
    pywin32 installed; the import error fires lazily when ``start()`` runs."""
    vd = _WindowsVirtualDesktop()
    assert vd._desktop is None
    assert vd._original_handle == 0


@pytest.mark.unit
def test_windows_desktop_stop_is_idempotent_without_start():
    """``stop()`` after never calling ``start()`` must be a no-op, so
    ``__exit__`` from a failed launch can call it unconditionally."""
    vd = _WindowsVirtualDesktop()
    vd.stop()
    vd.stop()
    assert vd._desktop is None
    assert vd._original_handle == 0
