import pytest

from invisible_playwright._fpforge import generate_profile
from invisible_playwright.prefs import translate_profile_to_prefs


@pytest.mark.unit
def test_translate_includes_gpu_renderer_windows():
    """On Windows, renderer/vendor are cleared so ANGLE reports native hardware."""
    p = generate_profile(seed=42)
    prefs = translate_profile_to_prefs(p)
    assert prefs["zoom.stealth.webgl.renderer"] == ""
    assert prefs["zoom.stealth.webgl.vendor"] == ""


@pytest.mark.unit
def test_translate_includes_screen():
    p = generate_profile(seed=42)
    prefs = translate_profile_to_prefs(p)
    assert prefs["zoom.stealth.screen.width"] == p.screen.width
    assert prefs["zoom.stealth.screen.height"] == p.screen.height


@pytest.mark.unit
def test_translate_is_deterministic_per_seed():
    a = translate_profile_to_prefs(generate_profile(seed=42))
    b = translate_profile_to_prefs(generate_profile(seed=42))
    assert a == b


@pytest.mark.unit
def test_translate_varies_across_seeds():
    a = translate_profile_to_prefs(generate_profile(seed=1))
    b = translate_profile_to_prefs(generate_profile(seed=2))
    assert a != b


@pytest.mark.unit
def test_translate_has_stealth_baseline_constants():
    p = generate_profile(seed=42)
    prefs = translate_profile_to_prefs(p)
    assert prefs.get("privacy.resistFingerprinting") is False
    assert "media.peerconnection.enabled" in prefs
