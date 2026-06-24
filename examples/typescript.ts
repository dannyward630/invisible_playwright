import { spawnSync } from "node:child_process";
import { firefox } from "playwright";

type InvisibleConfig = {
  launchOptions: Record<string, unknown> & {
    env?: Record<string, string>;
  };
  contextOptions: Record<string, unknown>;
};

function nodeEnv(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => {
      return entry[1] !== undefined;
    }),
  );
}

function invisibleConfig(args: string[]): InvisibleConfig {
  const result = spawnSync(
    "python",
    ["-m", "invisible_playwright", "launch-config", ...args],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || "failed to build invisible_playwright config");
  }
  return JSON.parse(result.stdout) as InvisibleConfig;
}

async function main() {
  const config = invisibleConfig([
    "--seed",
    "42",
    "--locale",
    "en-US",
    "--timezone",
    "America/New_York",
  ]);

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
