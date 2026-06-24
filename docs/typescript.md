# TypeScript / Node Playwright

`invisible_playwright` is still a Python package, but Node and TypeScript
callers can use the same patched Firefox binary and the same sampled stealth
profile by asking the Python CLI for a launch config.

Install the Python wrapper and fetch the binary once:

```bash
python -m pip install git+https://github.com/dannyward630/invisible_playwright.git
python -m invisible_playwright fetch
```

Install Playwright in your Node project:

```bash
npm install playwright@1.55.0
```

Generate a config:

```bash
python -m invisible_playwright launch-config \
  --seed 42 \
  --locale auto \
  --timezone auto \
  --pretty
```

The command emits JSON with:

- `launchOptions`: pass to `firefox.launch(...)`.
- `contextOptions`: pass intact to `browser.newContext(...)`; it carries
  viewport, screen, timezone, locale, and the matching `Accept-Language`
  header.
- `playwrightVersion`: the Node Playwright version validated against the
  current patched Firefox Juggler protocol.
- `requiresVirtualDisplay`: true when `--headless` was requested on Linux.

Minimal TypeScript example:

```typescript
import { spawnSync } from "node:child_process";
import { firefox } from "playwright";

const configProcess = spawnSync(
  "python",
  [
    "-m",
    "invisible_playwright",
    "launch-config",
    "--seed",
    "42",
    "--locale",
    "auto",
    "--timezone",
    "auto",
  ],
  { encoding: "utf8" },
);

if (configProcess.status !== 0) {
  throw new Error(configProcess.stderr || "failed to build invisible_playwright config");
}

function nodeEnv(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => {
      return entry[1] !== undefined;
    }),
  );
}

async function main() {
  const config = JSON.parse(configProcess.stdout);
  const browser = await firefox.launch({
    ...config.launchOptions,
    env: {
      ...nodeEnv(),
      ...(config.launchOptions.env ?? {}),
    },
  });

  const context = await browser.newContext(config.contextOptions);
  const page = await context.newPage();
  await page.goto("https://example.com");
  console.log(await page.title());
  await browser.close();
}

void main();
```

Notes:

- `launchOptions.headless` is intentionally `false`. The patched Firefox should
  run through the normal headed rendering pipeline for fingerprint coherence.
- Use the emitted `playwrightVersion` value for Node/TypeScript projects.
  Newer Playwright drivers can send protocol fields older patched Firefox
  binaries do not understand.
- If you typecheck with a newer TypeScript compiler against Playwright 1.55,
  enable `skipLibCheck` for third-party declaration files.
- On Linux, use `xvfb-run` or another display server when you want hidden
  operation.
- On Windows and macOS, `--headless` enables the patched binary's window cloak
  prefs while still launching headed internally.
- `--locale auto` derives a common regional locale from the resolved timezone
  when one is available (for example, `Europe/Warsaw` -> `pl-PL`). With
  `--timezone auto`, the CLI resolves the session timezone before emitting
  JSON; if direct no-proxy lookup falls back to the host default, it omits
  timezone fields rather than emitting the literal string `"auto"`.
- When proxy arguments are present, the CLI resolves the proxy egress once and
  includes `STEALTHFOX_WEBRTC_PUBLIC_IP` / `STEALTHFOX_WEBRTC_DISABLE_IPV6` in
  `launchOptions.env`, matching the Python wrapper's WebRTC behavior.
- Auto locale aligns `navigator.language`, `navigator.languages`, the Firefox
  `intl.accept_languages` pref, and the context `Accept-Language` header; the
  current patched Firefox build can still report its bundled runtime default
  from bare `Intl.*().resolvedOptions().locale`.
- SOCKS proxies are written into Firefox prefs. HTTP and HTTPS proxies are
  returned as Playwright `proxy` launch options.
- Proxy servers must include an explicit scheme and port, such as
  `socks5://gw.example:1080` or `http://gw.example:8080`; unsupported schemes,
  bare `host:port` values, embedded credentials, and path/query fragments fail
  fast before JSON is emitted.
- `python -m invisible_playwright network-probe` launches the same patched
  Firefox path and emits browser-side status, final URL, TLS/HTTP fingerprint
  JSON when the response body is JSON, and cookie metadata. It is useful when a
  Node/TypeScript integration needs to compare its target-site result against
  the wrapper's direct browser network behavior.
- For exact reproducibility, pass `--seed`. Without it, each config command
  samples a fresh profile.
