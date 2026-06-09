"""Download and cache the patched Firefox binary from GitHub Releases."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

import platformdirs
import requests

from .constants import (
    ARCHIVE_NAME,
    BINARY_ENTRY_REL,
    BINARY_VERSION,
    GEOIP_ASSET,
    GEOIP_MMDB_NAME,
    GEOIP_MMDB_VERSION,
    GEOIP_RELEASE_URL_TEMPLATE,
    RELEASE_URL_TEMPLATE,
)


def _github_token() -> str | None:
    return os.environ.get("STEALTHFOX_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")


def _parse_owner_repo(template: str) -> tuple[str, str]:
    """Extract (owner, repo) from RELEASE_URL_TEMPLATE."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/", template)
    if not m:
        raise RuntimeError(f"cannot parse owner/repo from {template!r}")
    return m.group(1), m.group(2)


def cache_root() -> Path:
    """Directory where all cached binaries live."""
    return Path(platformdirs.user_cache_dir("invisible-playwright"))


def cache_dir_for_version(version: str = BINARY_VERSION) -> Path:
    return cache_root() / version


def _resolve_asset_url(tag: str, asset_name: str) -> str:
    """Return a downloadable URL for the asset.

    For private repos the direct `releases/download/<tag>/<asset>` URL returns
    404 even with a token, so we resolve via the API: list assets for the
    release tag, find the one matching `asset_name`, and use its API URL with
    `Accept: application/octet-stream` (which 302-redirects to a signed URL).
    For public repos the direct URL still works without a token.
    """
    token = _github_token()
    if not token:
        return RELEASE_URL_TEMPLATE.format(tag=tag, asset=asset_name)
    owner, repo = _parse_owner_repo(RELEASE_URL_TEMPLATE)
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    r = requests.get(api, headers={"Authorization": f"token {token}"}, timeout=30)
    r.raise_for_status()
    for a in r.json().get("assets", []):
        if a.get("name") == asset_name:
            return a["url"]
    raise RuntimeError(f"asset {asset_name!r} not found in release {tag!r}")


def _download_file(url: str, dst: Path, chunk_size: int = 1 << 16) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    headers: dict[str, str] = {}
    token = _github_token()
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"token {token}"
        headers["Accept"] = "application/octet-stream"
    with requests.get(url, stream=True, timeout=60, headers=headers) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size):
                if chunk:
                    f.write(chunk)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_checksums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            # sha256sum uses ' *' or '  ' prefix for binary vs text mode
            key = parts[-1].lstrip("*")
            out[key] = parts[0]
    return out


def _extract(archive: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dst)
    elif archive.name.endswith(".tar.gz") or archive.suffix in {".tgz", ".gz"}:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dst)
    else:
        raise RuntimeError(f"unknown archive format: {archive}")


def _post_extract_darwin(app_root: Path, entry: Path) -> None:
    """Make an ad-hoc-signed .app launchable on macOS.

    The .app is downloaded via requests (no Finder quarantine attached), but we
    strip com.apple.quarantine defensively and ensure the inner binary is
    executable. We exec the inner binary directly (not via LaunchServices), so
    Gatekeeper's first-launch prompt does not apply; the ad-hoc signature
    (applied in release.yml) is what lets the arm64 Mach-O run at all.
    """
    app = app_root
    # walk up to the .app bundle dir if entry points inside it
    for parent in entry.parents:
        if parent.name.endswith(".app"):
            app = parent
            break
    try:
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(app)], check=False)
    except FileNotFoundError:
        pass
    try:
        entry.chmod(0o755)
    except OSError:
        pass


def ensure_binary(version: str = BINARY_VERSION) -> Path:
    """Return a path to a runnable Firefox executable. Download if needed."""
    plat = sys.platform
    mach = platform.machine()
    asset = ARCHIVE_NAME(plat, mach)
    entry_rel = BINARY_ENTRY_REL.get(plat)
    if entry_rel is None:
        raise NotImplementedError(f"no binary entry for platform {plat}")

    version_dir = cache_dir_for_version(version)
    entry = version_dir / entry_rel
    if entry.exists():
        return entry

    url_archive = _resolve_asset_url(version, asset)
    url_sums = _resolve_asset_url(version, "checksums.txt")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        archive_path = tmp / asset
        _download_file(url_archive, archive_path)
        sums_path = tmp / "checksums.txt"
        _download_file(url_sums, sums_path)
        sums = _parse_checksums(sums_path.read_text())
        expected = sums.get(asset)
        if expected is None:
            raise RuntimeError(f"no SHA256 for {asset} in checksums.txt")
        actual = _sha256_file(archive_path)
        if actual.lower() != expected.lower():
            raise RuntimeError(
                f"SHA256 mismatch for {asset}: got {actual}, expected {expected}"
            )
        _extract(archive_path, version_dir)

    if plat == "darwin":
        _post_extract_darwin(version_dir, entry)

    if not entry.exists():
        raise RuntimeError(f"binary not found after extraction: {entry}")
    return entry


# ─────────────────────────────────────────────────────────────────────────
#  GeoIP mmdb (timezone="auto" → map egress IP → IANA zone)
#
#  daijro/geoip-all-in-one is rebuilt WEEKLY, so we don't pin a tag. We cache
#  the latest mmdb and, once it's older than GEOIP_REFRESH_DAYS, re-check the
#  latest release and pull a newer build if one exists. Net effect: no download
#  (not even an API call) on a launch within the window; auto-refresh after it;
#  a stale cache is reused when offline rather than breaking the launch.
# ─────────────────────────────────────────────────────────────────────────
GEOIP_REFRESH_DAYS = 7  # matches daijro's weekly rebuild cadence


def _geoip_root() -> Path:
    return cache_root() / "geoip"


def _geoip_check_marker() -> Path:
    return _geoip_root() / ".last_check"


def _cached_geoip_mmdb() -> Path | None:
    """Newest cached mmdb across tag dirs, or None. Tag dirs are date strings
    (e.g. ``2026.06.03``) so a lexical sort is chronological."""
    root = _geoip_root()
    if not root.exists():
        return None
    cands = sorted(root.glob("*/*.mmdb"))
    return cands[-1] if cands else None


def _geoip_cache_fresh(max_age_days: int) -> bool:
    marker = _geoip_check_marker()
    if not marker.exists():
        return False
    return (time.time() - marker.stat().st_mtime) < max_age_days * 86400


def _touch_geoip_marker() -> None:
    m = _geoip_check_marker()
    m.parent.mkdir(parents=True, exist_ok=True)
    m.touch()


def _latest_geoip_tag() -> str:
    """Latest ``daijro/geoip-all-in-one`` release tag via the GitHub API."""
    headers = {"Accept": "application/vnd.github+json"}
    token = _github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    r = requests.get(
        f"https://api.github.com/repos/{GEOIP_REPO}/releases/latest",
        headers=headers, timeout=15,
    )
    r.raise_for_status()
    tag = r.json().get("tag_name")
    if not tag:
        raise RuntimeError("no tag_name in geoip-all-in-one latest release")
    return tag


def _download_geoip_tag(tag: str) -> Path:
    """Download + extract a specific tag's mmdb if not already cached."""
    dst_dir = _geoip_root() / tag
    target = dst_dir / GEOIP_MMDB_NAME
    if not target.exists():
        url = GEOIP_RELEASE_URL_TEMPLATE.format(tag=tag, asset=GEOIP_ASSET)
        dst_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / GEOIP_ASSET
            _download_file(url, archive)
            _extract(archive, dst_dir)
    if target.exists():
        return target
    # asset name inside the zip may differ from GEOIP_MMDB_NAME
    found = sorted(dst_dir.glob("*.mmdb"))
    if found:
        return found[0]
    raise RuntimeError(f"geoip mmdb not found after extraction in {dst_dir}")


def _prune_old_geoip_tags(keep: str) -> None:
    """Drop every cached tag dir except ``keep`` to bound disk usage."""
    root = _geoip_root()
    if not root.exists():
        return
    for d in root.iterdir():
        if d.is_dir() and d.name != keep:
            shutil.rmtree(d, ignore_errors=True)


def geoip_mmdb_path() -> Path | None:
    """Path to the currently-cached mmdb (newest tag), or None if none cached."""
    return _cached_geoip_mmdb()


def ensure_geoip_mmdb(max_age_days: int = GEOIP_REFRESH_DAYS) -> Path:
    """Return a geoip mmdb, kept fresh against daijro's weekly rebuild.

    Resolution order:
      1. ``STEALTHFOX_GEOIP_MMDB`` env → use that file (user-supplied / test).
      2. A cached mmdb younger than ``max_age_days`` → use it (no network).
      3. Else ask GitHub for the latest tag, download it if not already cached,
         prune older tags, and reset the freshness timer.
      4. If the API/download is unreachable but a cached mmdb exists → use it
         (and reset the timer so we don't hammer the API while offline).
      5. Cold cache + no network → fall back to the pinned ``GEOIP_MMDB_VERSION``;
         if that download also fails, raise.
    """
    override = os.environ.get("STEALTHFOX_GEOIP_MMDB")
    if override:
        p = Path(override)
        if not p.exists():
            raise RuntimeError(f"STEALTHFOX_GEOIP_MMDB points to a missing file: {p}")
        return p

    cached = _cached_geoip_mmdb()
    if cached and _geoip_cache_fresh(max_age_days):
        return cached

    try:
        tag = _latest_geoip_tag()
    except Exception:
        if cached:
            _touch_geoip_marker()  # recheck after the window; don't hammer
            return cached
        tag = GEOIP_MMDB_VERSION   # cold cache + API down → pinned fallback

    mmdb = _download_geoip_tag(tag)
    _prune_old_geoip_tags(mmdb.parent.name)
    _touch_geoip_marker()
    return mmdb
