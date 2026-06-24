"""Command-line interface for invisible_playwright."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from typing import Any

from . import __version__
from .config import build_playwright_launch_config
from .constants import (
    ARCHIVE_NAME,
    BINARY_VERSION,
    FIREFOX_UPSTREAM_VERSION,
    PLAYWRIGHT_DRIVER_VERSION,
    RELEASE_URL_TEMPLATE,
)
from .download import cache_root, ensure_binary
from .launcher import InvisiblePlaywright
from ._proxy import proxy_is_set


def _proxy_from_args(args: argparse.Namespace) -> dict | None:
    proxy = None
    if args.proxy_server:
        proxy = {"server": args.proxy_server}
        if args.proxy_username:
            proxy["username"] = args.proxy_username
        if args.proxy_password:
            proxy["password"] = args.proxy_password
    return proxy


def _cmd_fetch(args: argparse.Namespace) -> int:
    # --force: re-download even if already cached (drop the cached version dir,
    # then let ensure_binary fetch it fresh). Useful to recover a corrupted cache
    # or re-pull after a re-published release.
    if getattr(args, "force", False):
        from .download import cache_dir_for_version
        d = cache_dir_for_version()
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    path = ensure_binary()
    print(path)
    return 0


def _cmd_path(_args: argparse.Namespace) -> int:
    try:
        path = ensure_binary()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(path)
    return 0


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"invisible_playwright {__version__}")
    print(f"BINARY_VERSION={BINARY_VERSION} (Firefox {FIREFOX_UPSTREAM_VERSION})")
    return 0


def _cmd_clear_cache(_args: argparse.Namespace) -> int:
    root = cache_root()
    if root.exists():
        shutil.rmtree(root)
        print(f"removed: {root}")
    else:
        print(f"nothing to remove: {root}")
    return 0


def _json_obj(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


def _cmd_launch_config(args: argparse.Namespace) -> int:
    proxy = _proxy_from_args(args)
    humanize: bool | float
    if args.no_humanize:
        humanize = False
    elif args.humanize_max is not None:
        humanize = args.humanize_max
    else:
        humanize = True
    try:
        config = build_playwright_launch_config(
            seed=args.seed,
            pin=args.pin_json,
            locale=args.locale,
            timezone=args.timezone,
            extra_prefs=args.extra_prefs_json,
            humanize=humanize,
            headless=args.headless,
            proxy=proxy,
            binary_path=args.binary_path,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    indent = 2 if args.pretty else None
    print(json.dumps(config, indent=indent, sort_keys=True))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    proxy = _proxy_from_args(args)
    try:
        from ._geo import prepare_session_geo, resolve_session_locale
        from .prefs import accept_language_header

        geo = prepare_session_geo(args.timezone, proxy)
        locale = resolve_session_locale(args.locale, geo.timezone)
        asset = ARCHIVE_NAME(sys.platform, platform.machine())
        report = {
            "wrapperVersion": __version__,
            "binaryVersion": BINARY_VERSION,
            "firefoxVersion": FIREFOX_UPSTREAM_VERSION,
            "playwrightVersion": PLAYWRIGHT_DRIVER_VERSION,
            "platform": sys.platform,
            "machine": platform.machine(),
            "archive": asset,
            "releaseUrl": RELEASE_URL_TEMPLATE.format(tag=BINARY_VERSION, asset=asset),
            "proxyConfigured": proxy_is_set(proxy),
            "timezone": geo.timezone,
            "egressIp": geo.egress_ip,
            "locale": locale,
            "acceptLanguage": accept_language_header(locale),
        }
        if not args.skip_binary:
            report["binaryPath"] = str(ensure_binary())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    indent = 2 if args.pretty else None
    print(json.dumps(report, indent=indent, sort_keys=True))
    return 0


def _cookie_report(cookie: dict[str, Any], *, include_values: bool) -> dict[str, Any]:
    value = cookie.get("value") or ""
    report = {
        "name": cookie.get("name"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "expires": cookie.get("expires"),
        "secure": cookie.get("secure"),
        "httpOnly": cookie.get("httpOnly"),
        "sameSite": cookie.get("sameSite"),
        "valueLength": len(value),
    }
    if include_values:
        report["value"] = value
    return report


def _cmd_network_probe(args: argparse.Namespace) -> int:
    proxy = _proxy_from_args(args)
    try:
        with InvisiblePlaywright(
            seed=args.seed,
            locale=args.locale,
            timezone=args.timezone,
            headless=args.headless,
            proxy=proxy,
            binary_path=args.binary_path,
        ) as browser:
            page = browser.new_page()
            response = page.goto(
                args.url,
                wait_until=args.wait_until,
                timeout=int(args.timeout * 1000),
            )
            status = response.status if response is not None else None
            headers = response.headers if response is not None else {}
            content_type = headers.get("content-type") or headers.get("Content-Type") or ""
            title = page.title()
            if response is not None and "json" in content_type.lower():
                body_text = response.text()
            else:
                body_text = page.locator("body").inner_text(timeout=5000)
            try:
                body_json: Any = json.loads(body_text)
            except json.JSONDecodeError:
                body_json = None
            cookies = [
                _cookie_report(cookie, include_values=args.include_cookie_values)
                for cookie in page.context.cookies()
            ]
            report: dict[str, Any] = {
                "url": args.url,
                "finalUrl": page.url,
                "status": status,
                "ok": bool(response.ok) if response is not None else False,
                "contentType": content_type,
                "title": title,
                "proxyConfigured": proxy_is_set(proxy),
                "cookieCount": len(cookies),
                "cookies": cookies,
            }
            if body_json is not None:
                report["bodyJson"] = body_json
            else:
                report["bodyTextSample"] = body_text[: args.body_sample_chars]
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(report, indent=indent, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="invisible-playwright", description="invisible_playwright CLI")
    # Top-level `--version` / `-V` flag so `python -m invisible_playwright --version`
    # works (Python convention), in addition to the existing `version` subcommand.
    p.add_argument(
        "-V", "--version", action="version",
        version=f"invisible_playwright {__version__} (BINARY_VERSION={BINARY_VERSION}, Firefox {FIREFOX_UPSTREAM_VERSION})",
    )
    sub = p.add_subparsers(dest="cmd")

    fetch_p = sub.add_parser("fetch", help="download the patched Firefox binary")
    fetch_p.add_argument("--force", action="store_true",
                         help="re-download even if already cached")
    sub.add_parser("path", help="print the absolute path to the cached binary")
    sub.add_parser("version", help="print wrapper and binary versions")
    sub.add_parser("clear-cache", help="remove all cached binaries")
    cfg_p = sub.add_parser(
        "launch-config",
        help="emit JSON Playwright launch/context options for Python, Node, or TypeScript callers",
    )
    cfg_p.add_argument("--seed", type=int, help="deterministic fingerprint seed")
    cfg_p.add_argument(
        "--locale",
        default="en-US",
        help='BCP-47 locale, e.g. en-US, or "auto" to derive it from --timezone',
    )
    cfg_p.add_argument("--timezone", default="", help="IANA timezone, e.g. America/New_York")
    cfg_p.add_argument("--headless", action="store_true",
                       help="wrapper-style hidden headed mode; Linux callers must provide Xvfb")
    cfg_p.add_argument("--binary-path", help="use an existing Firefox binary instead of fetching")
    cfg_p.add_argument("--proxy-server", help="proxy server URL, e.g. socks5://host:1080")
    cfg_p.add_argument("--proxy-username", help="proxy username")
    cfg_p.add_argument("--proxy-password", help="proxy password")
    cfg_p.add_argument("--pin-json", type=_json_obj, help="JSON object of pinned fingerprint fields")
    cfg_p.add_argument("--extra-prefs-json", type=_json_obj, help="JSON object of extra Firefox prefs")
    cfg_p.add_argument("--no-humanize", action="store_true", help="disable Bezier mouse humanization")
    cfg_p.add_argument("--humanize-max", type=float, help="max humanized mouse move time in seconds")
    cfg_p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    doctor_p = sub.add_parser(
        "doctor",
        help="emit JSON diagnostics for release, binary, proxy egress, timezone, and locale",
    )
    doctor_p.add_argument(
        "--locale",
        default="en-US",
        help='BCP-47 locale, e.g. en-US, or "auto" to derive it from --timezone',
    )
    doctor_p.add_argument("--timezone", default="", help="IANA timezone, e.g. America/New_York")
    doctor_p.add_argument("--proxy-server", help="proxy server URL, e.g. socks5://host:1080")
    doctor_p.add_argument("--proxy-username", help="proxy username")
    doctor_p.add_argument("--proxy-password", help="proxy password")
    doctor_p.add_argument("--skip-binary", action="store_true", help="do not fetch or inspect the binary cache")
    doctor_p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    probe_p = sub.add_parser(
        "network-probe",
        help="launch patched Firefox and emit JSON network/TLS/cookie diagnostics for a URL",
    )
    probe_p.add_argument(
        "url",
        nargs="?",
        default="https://tls.peet.ws/api/all",
        help="URL to probe; defaults to tls.peet.ws browser TLS fingerprint JSON",
    )
    probe_p.add_argument("--seed", type=int, help="deterministic fingerprint seed")
    probe_p.add_argument(
        "--locale",
        default="en-US",
        help='BCP-47 locale, e.g. en-US, or "auto" to derive it from --timezone',
    )
    probe_p.add_argument("--timezone", default="", help="IANA timezone, e.g. America/New_York")
    probe_p.add_argument("--headless", action="store_true",
                         help="wrapper-style hidden headed mode; Linux callers must provide Xvfb")
    probe_p.add_argument("--binary-path", help="use an existing Firefox binary instead of fetching")
    probe_p.add_argument("--proxy-server", help="proxy server URL, e.g. socks5://host:1080")
    probe_p.add_argument("--proxy-username", help="proxy username")
    probe_p.add_argument("--proxy-password", help="proxy password")
    probe_p.add_argument(
        "--wait-until",
        choices=("commit", "domcontentloaded", "load", "networkidle"),
        default="domcontentloaded",
        help="Playwright page.goto wait state",
    )
    probe_p.add_argument("--timeout", type=float, default=45.0, help="navigation timeout in seconds")
    probe_p.add_argument(
        "--body-sample-chars",
        type=int,
        default=4000,
        help="max non-JSON body characters included in the report",
    )
    probe_p.add_argument(
        "--include-cookie-values",
        action="store_true",
        help="include raw cookie values in output; default only reports value lengths",
    )
    probe_p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        # argparse-conventional: print usage + error message to stderr, exit 2.
        # We can't keep `required=True` on the subparsers because that breaks
        # the top-level `--version` flag (argparse demands a subcommand even
        # when --version is the only token). parser.error() preserves the
        # original "no subcommand" exit semantics tests expect.
        parser.error(
            "a subcommand is required (try --help, --version, or one of: "
            "fetch, path, version, clear-cache, launch-config, doctor, network-probe)"
        )
    dispatch = {
        "fetch": _cmd_fetch,
        "path": _cmd_path,
        "version": _cmd_version,
        "clear-cache": _cmd_clear_cache,
        "launch-config": _cmd_launch_config,
        "doctor": _cmd_doctor,
        "network-probe": _cmd_network_probe,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
