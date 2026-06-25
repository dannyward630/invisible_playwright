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
    assert "network-probe" in r.stdout


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
    assert data["contextOptions"]["extraHTTPHeaders"]["Accept-Language"] == "de-DE, de"
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
    assert data["contextOptions"]["extraHTTPHeaders"]["Accept-Language"] == "pl-PL, pl"
    prefs = data["launchOptions"]["firefoxUserPrefs"]
    assert prefs["intl.accept_languages"] == "pl-PL, pl"


@pytest.mark.unit
def test_launch_config_subcommand_auto_timezone_resolves(tmp_path, monkeypatch, capsys):
    from invisible_playwright._geo import SessionGeo

    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    monkeypatch.setattr(
        "invisible_playwright.config.prepare_session_geo",
        lambda timezone, proxy: SessionGeo("Europe/Zurich", None),
    )

    rc = cli.main([
        "launch-config",
        "--seed", "42",
        "--locale", "auto",
        "--timezone", "auto",
        "--binary-path", str(fake_binary),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["resolvedTimezone"] == "Europe/Zurich"
    assert data["launchOptions"]["env"]["TZ"] == "Europe/Zurich"
    assert data["contextOptions"]["timezoneId"] == "Europe/Zurich"
    assert data["contextOptions"]["locale"] == "de-CH"
    assert data["contextOptions"]["extraHTTPHeaders"]["Accept-Language"] == "de-CH, de"


@pytest.mark.unit
def test_launch_config_subcommand_rejects_invalid_proxy(tmp_path, capsys):
    fake_binary = tmp_path / "firefox"
    fake_binary.write_text("x")

    rc = cli.main([
        "launch-config",
        "--seed", "42",
        "--binary-path", str(fake_binary),
        "--proxy-server", "proxy.example:8080",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "error:" in captured.err
    assert "must include a scheme" in captured.err


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
    assert data["acceptLanguage"] == "pl-PL, pl"
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


@pytest.mark.unit
def test_doctor_direct_proxy_reports_not_configured(monkeypatch, capsys):
    from invisible_playwright._geo import SessionGeo

    monkeypatch.setattr(
        "invisible_playwright._geo.prepare_session_geo",
        lambda timezone, proxy: SessionGeo("America/New_York", None),
    )

    rc = cli.main(["doctor", "--skip-binary", "--proxy-server", "direct://"])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["proxyConfigured"] is False


class _FakeResponse:
    status = 200
    ok = True
    url = "https://tls.peet.ws/api/all"
    headers = {
        "content-type": "application/json",
        "server": "test-edge",
        "set-cookie": "secret=value",
    }

    def text(self):
        return '{"tls": {"ja4": "t13d1617h2"}, "http2": {"akamai_fingerprint": "x"}}'


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    def inner_text(self, timeout=0):
        return self._text


class _FakeContext:
    def cookies(self):
        return [
            {
                "name": "_abck",
                "value": "abc123",
                "domain": ".example.test",
                "path": "/",
                "expires": 0,
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax",
            }
        ]


class _FakePage:
    url = "https://tls.peet.ws/api/all"
    context = _FakeContext()

    def __init__(self):
        self.response_handlers = []
        self.clicks = []
        self.waits = []

    def on(self, event, handler):
        assert event == "response"
        self.response_handlers.append(handler)

    def goto(self, url, wait_until, timeout):
        self.seen_goto = (url, wait_until, timeout)
        response = _FakeResponse()
        for handler in self.response_handlers:
            handler(response)
        return response

    def click(self, selector, timeout=0):
        self.clicks.append((selector, timeout))
        response = _FakeResponse()
        response.url = "https://example.test/login"
        response.status = 403
        response.ok = False
        response.headers = {
            "content-type": "text/html",
            "server": "AkamaiGHost",
            "set-cookie": "blocked=secret",
        }
        for handler in self.response_handlers:
            handler(response)

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)

    def title(self):
        return "probe"

    def locator(self, selector):
        assert selector == "body"
        return _FakeLocator('{"tls": {"ja4": "t13d1617h2"}, "http2": {"akamai_fingerprint": "x"}}')

    def evaluate(self, script):
        assert "navigator.webdriver" in script
        return {
            "userAgent": "Mozilla/5.0 Firefox/150.0.1",
            "webdriver": False,
            "languages": ["pl-PL", "pl"],
            "language": "pl-PL",
            "platform": "Win32",
            "hardwareConcurrency": 8,
            "deviceMemory": None,
            "pluginsLength": 5,
            "mimeTypesLength": 2,
            "timezone": "Europe/Warsaw",
            "viewport": {"width": 1280, "height": 720},
            "screen": {
                "width": 1920,
                "height": 1080,
                "availWidth": 1920,
                "availHeight": 1040,
                "colorDepth": 24,
                "pixelDepth": 24,
            },
            "devicePixelRatio": 1,
        }


class _FakeInvisiblePlaywright:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.seed = kwargs.get("seed") if kwargs.get("seed") is not None else 12345
        self._locale = kwargs.get("locale", "en-US")
        self._timezone = kwargs.get("timezone", "")
        self.page = _FakePage()
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def new_page(self):
        return self.page


@pytest.mark.unit
def test_network_probe_outputs_browser_network_diagnostics(monkeypatch, capsys):
    _FakeInvisiblePlaywright.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeInvisiblePlaywright)

    rc = cli.main([
        "network-probe",
        "--seed", "42",
        "--locale", "auto",
        "--timezone", "Europe/Warsaw",
        "--proxy-server", "socks5://gw.example:1080",
        "--binary-path", "/tmp/firefox",
        "--pretty",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["url"] == "https://tls.peet.ws/api/all"
    assert data["finalUrl"] == "https://tls.peet.ws/api/all"
    assert data["status"] == 200
    assert data["ok"] is True
    assert data["headers"]["server"] == "test-edge"
    assert data["headers"]["set-cookie"] == "[redacted]"
    assert data["proxyConfigured"] is True
    assert data["bodyJson"]["tls"]["ja4"] == "t13d1617h2"
    assert data["launch"]["seed"] == 42
    assert data["launch"]["headlessRequested"] is False
    assert data["launch"]["headlessMode"] == "headed"
    assert data["launch"]["locale"] == "auto"
    assert data["launch"]["timezone"] == "Europe/Warsaw"
    assert data["launch"]["binaryVersion"].startswith("firefox-")
    assert data["jsSnapshot"]["webdriver"] is False
    assert data["jsSnapshot"]["languages"] == ["pl-PL", "pl"]
    assert data["jsSnapshot"]["pluginsLength"] == 5
    assert data["jsSnapshot"]["timezone"] == "Europe/Warsaw"
    assert data["responses"][0]["headers"]["set-cookie"] == "[redacted]"
    assert data["responsesTruncated"] is False
    assert data["responsesDropped"] == 0
    assert data["cookieCount"] == 1
    assert data["cookies"][0]["name"] == "_abck"
    assert data["cookies"][0]["valueLength"] == 6
    assert "value" not in data["cookies"][0]
    instance = _FakeInvisiblePlaywright.instances[0]
    assert instance.kwargs["seed"] == 42
    assert instance.kwargs["locale"] == "auto"
    assert instance.kwargs["timezone"] == "Europe/Warsaw"
    assert instance.kwargs["proxy"] == {"server": "socks5://gw.example:1080"}
    assert instance.kwargs["binary_path"] == "/tmp/firefox"
    assert instance.page.seen_goto == (
        "https://tls.peet.ws/api/all",
        "domcontentloaded",
        45000,
    )


@pytest.mark.unit
def test_network_probe_can_include_cookie_values(monkeypatch, capsys):
    _FakeInvisiblePlaywright.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeInvisiblePlaywright)

    rc = cli.main(["network-probe", "--include-cookie-values"])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["cookies"][0]["value"] == "abc123"


class _FakeTextPage(_FakePage):
    url = "https://example.test/login"

    def goto(self, url, wait_until, timeout):
        self.seen_goto = (url, wait_until, timeout)
        response = _FakeResponse()
        response.headers = {"content-type": "text/html"}
        for handler in self.response_handlers:
            handler(response)
        return response

    def locator(self, selector):
        assert selector == "body"
        return _FakeLocator("Forbidden")


class _FakeTextBrowser(_FakeInvisiblePlaywright):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.page = _FakeTextPage()


class _FakeCspPage(_FakePage):
    def evaluate(self, script):
        raise RuntimeError("call to eval() blocked by CSP")


class _FakeCspBrowser(_FakeInvisiblePlaywright):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.page = _FakeCspPage()


@pytest.mark.unit
def test_network_probe_reports_text_body_sample(monkeypatch, capsys):
    _FakeTextBrowser.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeTextBrowser)

    rc = cli.main([
        "network-probe",
        "https://example.test/login",
        "--body-sample-chars", "4",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["bodyTextSample"] == "Forb"
    assert "bodyJson" not in data


@pytest.mark.unit
def test_network_probe_keeps_report_when_js_snapshot_is_blocked(monkeypatch, capsys):
    _FakeCspBrowser.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeCspBrowser)

    rc = cli.main(["network-probe"])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["status"] == 200
    assert "blocked by CSP" in data["jsSnapshot"]["error"]
    assert data["bodyJson"]["tls"]["ja4"] == "t13d1617h2"


@pytest.mark.unit
def test_network_probe_launch_metadata_marks_hidden_headed(monkeypatch, capsys):
    _FakeInvisiblePlaywright.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeInvisiblePlaywright)

    rc = cli.main(["network-probe", "--headless"])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["launch"]["headlessRequested"] is True
    assert data["launch"]["headlessMode"] == "hidden-headed"
    assert _FakeInvisiblePlaywright.instances[0].kwargs["headless"] is True


@pytest.mark.unit
def test_network_probe_clicks_selector_and_records_post_click_response(monkeypatch, capsys):
    _FakeInvisiblePlaywright.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeInvisiblePlaywright)

    rc = cli.main([
        "network-probe",
        "https://example.test/login",
        "--click-selector", "input[name=btnSubmit]",
        "--wait-after-click", "0.5",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["clickSelector"] == "input[name=btnSubmit]"
    assert data["responses"][-1]["url"] == "https://example.test/login"
    assert data["responses"][-1]["status"] == 403
    assert data["responses"][-1]["ok"] is False
    assert data["responses"][-1]["headers"]["server"] == "AkamaiGHost"
    assert data["responses"][-1]["headers"]["set-cookie"] == "[redacted]"
    page = _FakeInvisiblePlaywright.instances[0].page
    assert page.clicks == [("input[name=btnSubmit]", 45000)]
    assert page.waits == [500]


@pytest.mark.unit
def test_network_probe_response_log_respects_limit(monkeypatch, capsys):
    _FakeInvisiblePlaywright.instances = []
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FakeInvisiblePlaywright)

    rc = cli.main([
        "network-probe",
        "--click-selector", "button",
        "--max-responses", "1",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert len(data["responses"]) == 1
    assert data["responsesTruncated"] is True
    assert data["responsesDropped"] == 1


class _FailingInvisiblePlaywright:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        raise RuntimeError("launch failed")

    def __exit__(self, *args):
        return False


@pytest.mark.unit
def test_network_probe_errors_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(cli, "InvisiblePlaywright", _FailingInvisiblePlaywright)

    rc = cli.main(["network-probe"])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "error: launch failed" in captured.err
