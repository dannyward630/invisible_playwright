"""Canvas / WebGL render-stealth regression tests (binary-level, 2026-06-18).

Two patched-binary behaviours that must never regress, both needed for the
fingerprint to look like a real Windows browser to FOSS detectors (CreepJS,
FingerprintJS, BrowserLeaks) and to image-dedup font probes / fixed-hash
reference checks:

  1. Per-font canvas distinctness — whitelisted named fonts are backed by the
     host list-head glyphs (so measureText widths are host-independent), but each
     must still rasterise to a DISTINCT image at tiny probe sizes. Otherwise an
     image-dedup font probe collapses them to ~1 name and the reported font set
     looks fabricated. (C++: per-font sub-pixel draw offset in DrawText.)
  2. Solid WebGL readback purity under render-noise — a fixed solid-colour WebGL
     readback (which reference checks hash against a universal constant) must stay
     byte-exact even with per-seed render-noise enabled, while high-entropy
     renders stay noised. (C++: render-noise skips near-uniform WebGL readbacks.)

Runs against about:blank, no network/proxy. Part of the e2e release gate.
Run: pytest tests/test_canvas_render_stealth.py -m e2e -v
"""
from __future__ import annotations

import pytest

from invisible_playwright import InvisiblePlaywright
from invisible_playwright import prefs as _prefs
from invisible_playwright._fpforge import generate_profile
from invisible_playwright.constants import BINARY_VERSION

# Diverse-codepoint probe string — maximises per-font rendering differences, the
# way an image-dedup font probe drives a tiny canvas.
_PROBE = ("\U0001f6cd1>'`amlρiюदे來˦"
          "\U00025578に◌\U0002003eԩԨ")


def _named_fonts(limit: int = 30) -> list[str]:
    """The whitelisted NAMED fonts (absolute collapse-target width >= 10) for the
    test seed — these are the ones the per-font offset must keep distinct."""
    prof = generate_profile(42)
    metrics = _prefs._font_metrics_for_platform(prof._raw.get("font_metrics", "") or "")
    out: list[str] = []
    for ent in metrics.split(","):
        name, _, val = ent.partition("|")
        if not val:
            continue
        try:
            if float(val.replace("px", "")) >= 10.0:
                out.append(name)
        except ValueError:
            pass
    return out[:limit]


_FONTS = _named_fonts()


@pytest.fixture(scope="module")
def noised_page(firefox_binary):
    """Headless session with render-noise explicitly ON (positive hw_seed) so the
    purity / distinctness guards actually exercise the noise path."""
    with InvisiblePlaywright(
        seed=42,
        binary_path=firefox_binary,
        headless=True,
        extra_prefs={"zoom.stealth.fpp.hw_seed": 24680},
    ) as browser:
        p = browser.new_context().new_page()
        p.goto("about:blank", timeout=30_000)
        yield p


@pytest.mark.e2e
@pytest.mark.xfail(
    BINARY_VERSION == "firefox-12",
    strict=True,
    reason=(
        "firefox-12 archives collapse whitelisted named fonts to one canvas "
        "image; keep this as a binary-release blocker until the patched "
        "Firefox build restores per-font draw offsets"
    ),
)
def test_named_fonts_render_distinct_canvas_images(noised_page):
    """Each whitelisted named font must produce a DISTINCT tiny-canvas image so an
    image-dedup font probe keeps every name. Regression: without the per-font draw
    offset all whitelisted fonts share the list-head glyphs -> ~1-2 distinct
    images -> degenerate detected-font set."""
    assert len(_FONTS) >= 10, "expected a non-trivial named-font whitelist to probe"
    distinct = noised_page.evaluate(
        """(args) => {
            const [fonts, V] = args;
            const c = document.createElement('canvas'); c.width = 90; c.height = 12;
            const d = c.getContext('2d'); d.fillStyle = 'red';
            const seen = new Set();
            for (const f of fonts) {
                d.clearRect(0, 0, 90, 12);
                d.font = 'normal 4px "' + f + '"';
                d.fillText(V, 5, 8);
                seen.add(c.toDataURL());
            }
            return seen.size;
        }""",
        [_FONTS, _PROBE],
    )
    # broken (offset removed) collapses to ~1-2; require nearly all distinct.
    assert distinct >= len(_FONTS) - 2, \
        f"only {distinct}/{len(_FONTS)} distinct font images (per-font offset regressed?)"


@pytest.mark.e2e
def test_solid_webgl_readback_stays_pure_under_noise(noised_page):
    """A solid-colour WebGL readback must remain byte-exact (only {0,255}) with
    render-noise on. Regression: the noise drifted edge pixels 255->254 on some GL
    backends (Linux ANGLE-over-GL), breaking fixed-hash reference checks ('oe')."""
    res = noised_page.evaluate(
        """() => {
            const c = document.createElement('canvas'); c.width = 256; c.height = 24;
            const gl = c.getContext('webgl', {preserveDrawingBuffer: true});
            if (!gl) return {ok: false, reason: 'no-webgl'};
            gl.clearColor(1, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
            const buf = new Uint8Array(256 * 24 * 4);
            gl.finish(); gl.readPixels(0, 0, 256, 24, gl.RGBA, gl.UNSIGNED_BYTE, buf);
            const vals = new Set();
            for (let i = 0; i < buf.length; i++) vals.add(buf[i]);
            return {ok: true, vals: Array.from(vals).sort((a, b) => a - b)};
        }"""
    )
    if not res["ok"]:
        pytest.skip(res.get("reason", "webgl unavailable"))
    assert res["vals"] == [0, 255], \
        f"solid WebGL readback not pure under noise: values {res['vals']} (uniform-skip regressed?)"


# NOTE: "high-entropy WebGL still noised" is covered by test_webgl_noise_active.py
# (kept separate: it launches its own browsers, so it must not run while this
# module's shared `noised_page` browser is open — the sync API cannot nest).
