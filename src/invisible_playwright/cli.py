"""Command-line interface for invisible_playwright."""
from __future__ import annotations

import argparse
import shutil
import sys

from . import __version__
from .constants import BINARY_VERSION, FIREFOX_UPSTREAM_VERSION
from .download import cache_root, ensure_binary


def _cmd_fetch(_args: argparse.Namespace) -> int:
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="invisible-playwright", description="invisible_playwright CLI")
    # Top-level `--version` / `-V` flag so `python -m invisible_playwright --version`
    # works (Python convention), in addition to the existing `version` subcommand.
    p.add_argument(
        "-V", "--version", action="version",
        version=f"invisible_playwright {__version__} (BINARY_VERSION={BINARY_VERSION}, Firefox {FIREFOX_UPSTREAM_VERSION})",
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("fetch", help="download the patched Firefox binary")
    sub.add_parser("path", help="print the absolute path to the cached binary")
    sub.add_parser("version", help="print wrapper and binary versions")
    sub.add_parser("clear-cache", help="remove all cached binaries")
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
        parser.error("a subcommand is required (try --help, --version, or one of: fetch, path, version, clear-cache)")
    dispatch = {
        "fetch": _cmd_fetch,
        "path": _cmd_path,
        "version": _cmd_version,
        "clear-cache": _cmd_clear_cache,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
