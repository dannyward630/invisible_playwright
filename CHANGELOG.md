# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.4] - 2026-05-20

### Fixed
- [#13](https://github.com/feder-cr/invisible_playwright/issues/13): every page that threw an uncaught JS error (e.g. bunny.net) crashed the Playwright client with `TypeError: Cannot read properties of undefined (reading 'url')`. Root cause: upstream Playwright Juggler added a required `location` field to the `Page.uncaughtError` event in the 2026-05-07 roll ([microsoft/playwright@c8604ec](https://github.com/microsoft/playwright/commit/c8604ecd97)); our fork was carrying the pre-roll schema in every `firefox-N` build. Fix matches upstream — Runtime.js builds the `errorLocation`, PageAgent.js forwards it on both worker and runtime error paths, Protocol.js declares the schema field. Reporter: [@dionorgua](https://github.com/dionorgua).

### Changed
- `BINARY_VERSION` bumped from `firefox-3` to `firefox-4`. JS-only change inside `chrome/juggler/`; `xul.dll` and `firefox.exe` are byte-identical to `firefox-3`.

## [0.1.3] - 2026-05-19

### Changed
- `BINARY_VERSION` bumped from `firefox-2` to `firefox-3`. The new archives on both Windows and Linux are built from a clean clone of [feder-cr/invisible-firefox#stealth/150](https://github.com/feder-cr/invisible-firefox/tree/stealth/150) — the consolidated source-of-truth fork (renamed from `feder-cr/firefox`; the companion `feder-cr/firefox-stealth` patches repo was deleted, all patches now live as commits on top of `mozilla-firefox/firefox`).
- The patched Firefox archive now ships the **proper C++ implementation** of `windowUtils.jugglerSendMouseEvent`, replacing the JS shim from 0.1.2.

### C++ fixes landed in this release
- **C1+C2**: `setDownloadInterceptor` IDL + cpp (re-landed for FF150).
- **C4**: 5 `nsIDocShell` stealth attributes (`fileInputInterceptionEnabled`, `overrideHasFocus`, `bypassCSPEnabled`, `forceActiveState`, `disallowBFCache`).
- **C5**: `LauncherProcessWin.cpp` + `nsWindowsWMain.cpp` juggler-pipe handle inheritance — without this, the Playwright pipe disconnects immediately on launch.
- **C6**: `juggler-navigation-started-renderer` / `-browser` observer notifications in `nsDocShell.cpp` and `CanonicalBrowsingContext.cpp` — without these, `Page.ready` never fires and `ctx.new_page()` hangs.
- **C7 (partial)**: storage stub for `nsIDocShell.languageOverride`. Workaround `InvisiblePlaywright(locale="")` recommended until full BC FIELD port lands.

### Verified
- Both archives built from same source: feder-cr/invisible-firefox commit `68906f1f9c55`.
- Windows + Linux smoke suite green: launch, `ctx.new_page()`, `page.mouse.{move,down,up,click,wheel}`, `navigator.webdriver=false`, sannysoft 32/33 PASS.
- SHA256 published in `checksums.txt` on the `firefox-3` release.

### Notes
- This is the first release with a native Linux build of the patched binary (previous `firefox-3` draft mentioned shipping the Linux firefox-2 archive byte-for-byte; that no longer applies — Linux now has the full C++ patch series).

## [0.1.2] - 2026-05-18

### Changed
- `BINARY_VERSION` bumped from `firefox-1` to `firefox-2`. The patched Firefox archive on GitHub Releases now contains the JS fix from 0.1.1 (every `page.mouse.*` / `page.click()` / `locator.click()` / `mouse.wheel()` failure on the FF150 binary). Users on 0.1.1 must run `python -m invisible_playwright clear-cache && python -m invisible_playwright fetch` to pick up the new archive.

### Verified
- Archive integrity tests on both platforms: Windows zip extracted + booted via Playwright (`mouse.move + click + page.click(selector)` all succeed end-to-end), Linux tarball file-level checks (firefox/libxul.so sizes, byte-identity of patched JS files against Windows source). 21/21 assertions pass.
- SHA256 published in `checksums.txt` on the `firefox-2` release.

## [0.1.1] - 2026-05-18

### Fixed
- **Critical**: every `page.mouse.*`, `page.click(selector)`, `locator.click()`, `page.hover()`, `mouse.wheel()` failed on the patched Firefox 150 binary with `win.windowUtils.jugglerSendMouseEvent is not a function`. The Juggler JS was porting calls to a Playwright-specific C++ method that was never landed in the FF146→FF150 port; replaced with the Mozilla chrome-scope `win.synthesizeMouseEvent` helper which is present in FF150. Six call sites patched across `juggler/protocol/PageHandler.js` and `juggler/content/PageAgent.js`. Reporter: [@trob9](https://github.com/trob9) — [#9](https://github.com/feder-cr/invisible_playwright/issues/9).
- `_linkedBrowser.scrollRectIntoViewIfNeeded()` is now guarded at both call sites in `PageHandler.js` (`dispatchMouseEvent` and `dispatchWheelEvent`) — the method is not present on the shipped FF150 `<browser>` element, so the unguarded call threw before the mouse event was dispatched.

### Added
- `tests/test_mouse.py`: 12-case regression suite covering every patched code path (mouse.move/click/dblclick/right-click, modifiers, locator.click/hover, wheel, manual mousedown+up, off-viewport move, humanize intermediate moves, scroll-and-click on offscreen element). Test cases inspired by `microsoft/playwright-python/tests/async/test_click.py`.
- Community standards: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`.

### Notes
- The Stealthfox humanize Bezier expansion continues to fire intermediate `mousemove` events; the swap to `synthesizeMouseEvent` does not change the human-trajectory behavior (verified by test).
- The reCAPTCHA v3 score (0.90) and FingerprintPro / CreepJS results documented in the README are unaffected — `synthesizeMouseEvent` is a legitimate Mozilla helper that does not increase the anti-detect surface.
- A binary refresh of the patched Firefox archive on GitHub Releases is required for users to receive this fix (the Juggler JS is shipped inside the archive). The `BINARY_VERSION` will be bumped to `firefox-2` in that release.

## [0.1.0] - 2026-05-13

### Added
- Initial public release.
- `InvisiblePlaywright` sync and async context managers — drop-in replacement for `playwright.sync_api.Browser` / `async_api.Browser`.
- StealthFox humanize hook: Bezier-curve mouse trajectories enabled by default.
- `_fpforge` Bayesian fingerprint sampler with ~400 fields per session.
- CLI: `invisible-playwright fetch | path | version | clear-cache`.
- Pinnable fingerprint fields via `pin={...}` (see `docs/pinning.md`).
- SOCKS5 / SOCKS4 / HTTP / HTTPS proxy support with auth.
- Linux x86_64 and Windows x86_64 binary support.

[Unreleased]: https://github.com/feder-cr/invisible_playwright/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/feder-cr/invisible_playwright/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/feder-cr/invisible_playwright/releases/tag/v0.1.0
