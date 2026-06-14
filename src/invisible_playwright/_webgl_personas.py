"""Empirically-calibrated WebGL GPU personas for Windows ANGLE D3D11.

We expose a FALSE GPU (this is a multi-user tool — never leak each host's real GPU),
chosen deterministically per seed from a small set of renderer-string "buckets" that
Firefox's SanitizeRenderer emits and that FP Pro's tampering_ml scores as CLEAN.

## What actually gates a persona (calibrated 2026-06-14, supersedes the old theory)

The blocker is NOT anti_detect and NOT a "render-vs-renderer" check. It is FP Pro's
**tampering_ml** (gate <=0.5), a holistic ML coherence score. We reverse-engineered its
GPU sensitivity with single-variable A/Bs on demo.fingerprint.com (deterministic per
(seed, renderer, IP); tools in tests/_gpu_isolate.py / _gpu_landscape.py / _gpu_sweep.py /
_gpu_sweep2.py / _gpu_persona_pure.py). Findings:

  1. tampering_ml = f(renderer STRING, seed baseline = canvas/audio). The renderer string
     carries a STABLE per-bucket penalty; the seed sets the floor it adds to.
  2. gpu_class is IRRELEVANT to tampering_ml (nv_980 scored identically on mid_range /
     high_end / premium / workstation). So pairing a fake GPU with a "matching" hardware
     tier does NOT help the score (we still set a coherent class — see gpu_class below —
     for OTHER detectors that cross-check cores/screen, just not for this).
  3. It is NOT render-consistency: a cross-vendor AMD string is CLEAN on our Intel-Arc
     host. So the real silicon's pixels are not the dominant signal; falsifying to a
     different vendor works — IF the string is one FP Pro scores low.

Sweep over all 10 Windows SanitizeRenderer buckets x 10 seeds (clean = tml<=0.5 AND not
anti_detect), on our Intel Arc A750 host:
  - amd_r9 (Radeon R9 200 Series) ...... 10/10 clean, max tml 0.346   <- SHIP
  - intel_arc (Arc A750) ............... 10/10 clean, max tml 0.377   <- SHIP
  - amd_hd5850 ......................... 9/10 (fails the hardest seed)
  - amd_hd3200 / intel_hd .............. 6/10 (seed-dependent, risky)
  - intel_hd400 ........................ 3/10
  - ALL NVIDIA (8800/480/980) .......... 0/10 (penalized everywhere, ~0.7-0.99)
  - intel_945 (ancient Intel) .......... 0/10
So only TWO buckets are robustly clean across profiles. We ship exactly those, weighted
to real-world prevalence ("Radeon R9 200 Series" is the bucket for ALL modern AMD = a big
real slice; "Arc A750" covers Intel discrete = rarer). Cross-vendor, so the fleet is not a
single-GPU cluster. More names require lowering the seed floor first (see CAVEAT 2).

## ⚠️ CAVEATS
 1. HOST-INDEPENDENCE NOT PROVEN. Everything above was measured on ONE host (Intel Arc
    A750). The host's real render is embedded in the seed baseline, so the clean-bucket set
    *might* be host-dependent (on a real NVIDIA host, maybe nv_980 is clean and amd_r9 is
    not). This MUST be validated on a non-Arc machine before trusting it fleet-wide; if it
    turns out host-dependent, add a pre-launch host-GPU-class probe and pick a bucket per
    detected class. Until then: safe for Arc hosts (incl. the dev's), unvalidated elsewhere.
 2. DIVERSITY CEILING = 2 names because "hard" seeds (high canvas/audio floor, e.g. seed 4
    ~0.35) only stay clean on the 2 best buckets. Lowering that floor (an fpforge CPT fix —
    candidate: 8-channel audio + 1TB storage emitted on a mid_range profile) would unlock
    amd_hd5850 / intel_hd for more seeds => up to ~5 names. Follow-up, not done yet.

## Load-bearing format requirements (unchanged, still true)
 - renderer MUST end ", D3D11)" (full ANGLE wire format) or SanitizeRenderer returns
   "Generic Renderer" (a tell). The C++ passes our string through SanitizeRenderer, which
   buckets "AMD Radeon R9 200 Series" -> "Radeon R9 200 Series" and "Arc A750" -> itself.
 - the forced extension list MUST be the EXACT NATIVE ORDER getSupportedExtensions returns.
   The set+order is fixed by Firefox+ANGLE on D3D11 FL11_0 (VENDOR-INDEPENDENT — verified
   via 20-agent source study), so ONE list is correct for both personas. A reorder is caught
   (tampering_ml 0.34 -> 0.84). The lists below are the verbatim native-order Arc capture.

Calibration data + sweep tooling live in the local workbench (not shipped).
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional

# Vendor-independent ext lists (native order, Arc host capture). Identical for every persona
# because the set+order is fixed by Firefox+ANGLE on D3D11 FL11_0, not by the GPU vendor.
_EXT1 = (
    "ANGLE_instanced_arrays,EXT_blend_minmax,EXT_color_buffer_half_float,EXT_float_blend,"
    "EXT_frag_depth,EXT_shader_texture_lod,EXT_sRGB,EXT_texture_compression_bptc,"
    "EXT_texture_compression_rgtc,EXT_texture_filter_anisotropic,OES_element_index_uint,"
    "OES_fbo_render_mipmap,OES_standard_derivatives,OES_texture_float,OES_texture_float_linear,"
    "OES_texture_half_float,OES_texture_half_float_linear,OES_vertex_array_object,"
    "WEBGL_color_buffer_float,WEBGL_compressed_texture_s3tc,WEBGL_compressed_texture_s3tc_srgb,"
    "WEBGL_debug_renderer_info,WEBGL_debug_shaders,WEBGL_depth_texture,WEBGL_draw_buffers,"
    "WEBGL_lose_context,WEBGL_provoking_vertex"
)
_EXT2 = (
    "EXT_color_buffer_float,EXT_float_blend,EXT_texture_compression_bptc,"
    "EXT_texture_compression_rgtc,EXT_texture_filter_anisotropic,OES_draw_buffers_indexed,"
    "OES_texture_float_linear,OVR_multiview2,WEBGL_compressed_texture_s3tc,"
    "WEBGL_compressed_texture_s3tc_srgb,WEBGL_debug_renderer_info,WEBGL_debug_shaders,"
    "WEBGL_lose_context,WEBGL_provoking_vertex"
)


def _p(key, renderer, vendor, gpu_class, weight):
    return {"key": key, "renderer": renderer, "vendor": vendor,
            "gpu_class": gpu_class, "weight": weight, "ext1": _EXT1, "ext2": _EXT2}


# Only the two robustly-clean Windows buckets (calibration sweep 2026-06-14). Both discrete,
# so gpu_class=mid_range keeps cores/screen coherent with the declared GPU for OTHER detectors
# (gpu_class does NOT affect tampering_ml). Weights ~ real-world prevalence of the BUCKET:
# "Radeon R9 200 Series" represents ALL modern AMD (large real slice); "Arc A750" = Intel
# discrete (rarer). Cross-vendor => the fleet is not a single-GPU cluster.
_PERSONAS: List[Dict] = [
    _p("amd_radeon_r9", "ANGLE (AMD, AMD Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0, D3D11)",
       "Google Inc. (AMD)", "mid_range", 70),    # -> bucket "Radeon R9 200 Series"; tml 0.03-0.35
    _p("intel_arc_a750", "ANGLE (Intel, Intel(R) Arc(TM) A750 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
       "Google Inc. (Intel)", "mid_range", 30),  # -> bucket "Intel(R) Arc(TM) A750 Graphics"; tml 0.02-0.38
]

_TOTAL_W = sum(p["weight"] for p in _PERSONAS)

# ENABLED: we falsify the GPU on Windows/mac. Validated clean on an Intel Arc host (see the
# HOST-INDEPENDENCE caveat in the module docstring — unvalidated on non-Arc hosts). On Linux
# select_persona returns None: there prefs.py spoofs profile.gpu.renderer directly.
_ENABLED = True


def select_persona(seed: int) -> Optional[Dict]:
    """Deterministic, prevalence-weighted persona for this seed (None on Linux).

    Same seed -> same persona (fppro_consistency: identity stable per seed). Different seeds
    spread across the persona mix by weight. None on Linux (the sampled profile.gpu.renderer
    is spoofed directly there).
    """
    if not _ENABLED or sys.platform.startswith("linux") or not _PERSONAS:
        return None
    h = (int(seed) * 2654435761) % _TOTAL_W
    cum = 0
    for p in _PERSONAS:
        cum += p["weight"]
        if h < cum:
            return p
    return _PERSONAS[-1]


def forced_gpu_class(seed: int) -> Optional[str]:
    """The gpu_class the forge conditions the WHOLE bundle on (== the selected persona's class),
    so cores/screen/fonts stay coherent with the GPU we expose. Does NOT affect FP Pro
    tampering_ml (proven) but matters for detectors that cross-check hardware tier. None on Linux."""
    p = select_persona(seed)
    return p["gpu_class"] if p else None


# ── Render-noise seed pool (canvas/WebGL gamma) ──────────────────────────────
# zoom.stealth.fpp.hw_seed drives the per-seed canvas2D + WebGL readPixels gamma
# LUT in C++. The render-image HASH it produces is the DOMINANT FP Pro tampering_ml
# driver (proven 2026-06-14: holding a fixed profile and varying ONLY hw_seed moved
# tml 0.25->0.75). The monotonic gamma preserves the GPU's render structure, so some
# hw_seeds yield a "suspicious" render hash. We therefore DECOUPLE the render-noise
# seed from the identity seed and pick from a calibrated pool of hw_seeds that score
# CLEAN even on the hardest attribute profile (sweep 1..30 vs the worst seed: these
# 14 all gave tml<=0.285). Diversity is preserved (14 distinct render hashes spread
# across the population — real GPUs cluster to few canvas hashes anyway); identity
# stays per-seed (the rest of the fingerprint differs). Same seed -> same render seed
# (fppro_consistency holds).
# CAVEAT: the render hash = f(host GPU render, gamma), so this pool is calibrated on
# the Intel-Arc host. On other GPUs the clean set may differ (host-independence open,
# same as the personas) — Option B (substitution = GPU-independent render hash) would
# remove that dependency. Validate per-host or move to B before trusting fleet-wide.
CLEAN_RENDER_SEEDS = [19, 10, 28, 24, 23, 16, 11, 30, 17, 22, 3, 9, 12, 26]


def render_noise_seed(seed: int) -> int:
    """Deterministic clean render-noise seed for hw_seed (decoupled from identity).

    Maps the identity seed into CLEAN_RENDER_SEEDS so every session gets a calibrated
    clean canvas/WebGL render hash while keeping per-user diversity. Stable per seed."""
    return CLEAN_RENDER_SEEDS[(int(seed) * 2654435761) % len(CLEAN_RENDER_SEEDS)]
