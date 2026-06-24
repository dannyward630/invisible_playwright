import subprocess
import sys
import json
from pathlib import Path

import pytest

from invisible_playwright import cli


@pytest.mark.unit
def test_version_subcommand():
    r = subprocess.run(
        [sys.executable, "-m", "invisible_playwright", "version"],
        capture_output=True, text=True, check=True,
    )
    assert "firefox-" in r.stdout
    assert "invisible_playwright" in r.stdout.lower()


@pytest.mark.unit
def test_help_subcommand():
    r = subprocess.run(
        [sys.executable, "-m", "invisible_playwright", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "fetch" in r.stdout
    assert "path" in r.stdout
    assert "clear-cache" in r.stdout
    assert "launch-config" in r.stdout
    assert "doctor" in r.stdout


# CL1: clear-cache with existing cache prints "removed:" + path
@pytest.mark.unit
def test_clear_cache_with_existing_cache(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "existing-cache"
    cache.mkdir()
    (cache / "marker").write_text("x")
    monkeypatch.setattr("invisible_playwright.cli.cache_root", lambda: cache)

    rc = cli.main(["clear-cache"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.startswith("removed:")
    assert str(cache) in captured.out
    assert not cache.exists()


# CL2: clear-cache with no cache prints "nothing to remove:"
@pytest.mark.unit
def test_clear_cache_with_no_cache(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "missing-cache"
    assert not cache.exists()
    monkeypatch.setattr("invisible_playwright.cli.cache_root", lambda: cache)

    rc = cli.main(["clear-cache"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.startswith("nothing to remove:")
    assert str(cache) in captured.out


# CL3: path when binary exists prints path, exit 0
@pytest.mark.unit
def test_path_subcommand_when_binary_exists(tmp_path, monkeypatch, capsys):
    fake_binary = tmp_path / "firefox.exe"
    fake_binary.write_text("x")
    monkeypatch.setattr("invisible_playwright.cli.ensure_binary", lambda: fake_binary)

    rc = cli.main(["path"])

    captured = capsys.readouterr()
    assert rc == 0
    assert str(fake_binary) in captured.out
    assert captured.err == ""


# CL4: path when binary missing prints to stderr, exit 1
@pytest.mark.unit
def test_path_subcommand_when_binary_missing(monkeypatch, capsys):
    def boom():
        raise RuntimeError("download failed")
    monkeypatch.setattr("invisible_playwright.cli.ensure_binary", boom)

    rc = cli.main(["path"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err
    assert "download failed" in captured.err
    assert captured.out == ""


# CL5: no subcommand → argparse error, exit != 0
@pytest.mark.unit
def test_no_subcommand_errors():
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code != 0


# CL6: unknown subcommand → argparse error
@pytest.mark.unit
def test_unknown_subcommand_errors():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["bogus"])
    assert exc_info.value.code != 0


# Extra: fetch happy path with mocked ensure_binary
@pytest.mark.unit
def test_fetch_subcommand_prints_path(tmp_path, monkeypatch, capsys):
    fake_binary = tmp_path / "firefox.exe"
    fake_binary.write_text("x")
    monkeypatch.setattr("invisible_playwright.cli.ensure_binary", lambda: fake_binary)

    rc = cli.main(["fetch"])

    captured = capsys.readouterr()
    assert rc == 0
    assert str(fake_binary) in captured.out


@pytest.mark.unit
def test_launch_config_subcommand_outputs_json(tmp_path, capsys):
    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    rc = cli.main([
        "launch-config",
        "--seed", "42",
        "--locale", "de-DE",
        "--timezone", "Europe/Berlin",
        "--binary-path", str(fake_binary),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["seed"] == 42
    assert data["launchOptions"]["executablePath"] == str(fake_binary)
    assert data["launchOptions"]["headless"] is False
    assert data["launchOptions"]["env"]["TZ"] == "Europe/Berlin"
    assert data["contextOptions"]["locale"] == "de-DE"
    assert data["contextOptions"]["timezoneId"] == "Europe/Berlin"


@pytest.mark.unit
def test_launch_config_subcommand_auto_locale_uses_timezone(tmp_path, capsys):
    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    rc = cli.main([
        "launch-config",
        "--seed", "42",
        "--locale", "auto",
        "--timezone", "Europe/Warsaw",
        "--binary-path", str(fake_binary),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["contextOptions"]["locale"] == "pl-PL"
    prefs = data["launchOptions"]["firefoxUserPrefs"]
    assert prefs["intl.accept_languages"] == "pl-PL, pl"


@pytest.mark.unit
def test_launch_config_subcommand_accepts_json_overlays(tmp_path, capsys):
    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    rc = cli.main([
        "launch-config",
        "--seed", "42",
        "--binary-path", str(fake_binary),
        "--pin-json", '{"hardware.concurrency": 16}',
        "--extra-prefs-json", '{"custom.pref": "ok"}',
        "--no-humanize",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    prefs = data["launchOptions"]["firefoxUserPrefs"]
    assert prefs["zoom.stealth.hw_concurrency"] == 16
    assert prefs["custom.pref"] == "ok"
    assert prefs["stealthfox.humanize"] is False


@pytest.mark.unit
def test_doctor_subcommand_outputs_diagnostics(tmp_path, monkeypatch, capsys):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    monkeypatch.setattr(
        "invisible_playwright._geo.prepare_session_geo",
        lambda timezone, proxy: SessionGeo("Europe/Warsaw", "203.0.113.7"),
    )
    monkeypatch.setattr("invisible_playwright.cli.ensure_binary", lambda: fake_binary)

    rc = cli.main([
        "doctor",
        "--locale", "auto",
        "--timezone", "auto",
        "--proxy-server", "socks5://gw.example:1080",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["binaryVersion"].startswith("firefox-")
    assert data["playwrightVersion"]
    assert data["proxyConfigured"] is True
    assert data["timezone"] == "Europe/Warsaw"
    assert data["egressIp"] == "203.0.113.7"
    assert data["locale"] == "pl-PL"
    assert data["binaryPath"] == str(fake_binary)
    assert data["releaseUrl"].startswith("https://github.com/dannyward630/invisible_playwright/")


@pytest.mark.unit
def test_doctor_skip_binary_avoids_fetch(monkeypatch, capsys):
    from invisible_playwright._geo import SessionGeo

    monkeypatch.setattr(
        "invisible_playwright._geo.prepare_session_geo",
        lambda timezone, proxy: SessionGeo("America/New_York", None),
    )

    def boom():
        raise AssertionError("ensure_binary should not be called")

    monkeypatch.setattr("invisible_playwright.cli.ensure_binary", boom)

    rc = cli.main(["doctor", "--skip-binary"])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["timezone"] == "America/New_York"
    assert data["locale"] == "en-US"
    assert "binaryPath" not in data
