import subprocess
import sys


def test_version_subcommand():
    r = subprocess.run(
        [sys.executable, "-m", "invisible_playwright", "version"],
        capture_output=True, text=True, check=True,
    )
    assert "firefox-" in r.stdout
    assert "invisible_playwright" in r.stdout.lower()


def test_help_subcommand():
    r = subprocess.run(
        [sys.executable, "-m", "invisible_playwright", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "fetch" in r.stdout
    assert "path" in r.stdout
    assert "clear-cache" in r.stdout
