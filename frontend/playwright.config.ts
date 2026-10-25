import { defineConfig, devices } from "@playwright/test";

const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const e2ePort = runtimeEnv.KPD_E2E_PORT ?? "5173";
const baseURL = runtimeEnv.KPD_E2E_BASE_URL ?? `http://127.0.0.1:${e2ePort}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: false,
  workers: runtimeEnv.CI === "true" ? 1 : undefined,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: `npm run dev -- --port ${e2ePort} --strictPort`,
    url: baseURL,
    reuseExistingServer: runtimeEnv.CI !== "true",
    timeout: 120_000,
  },
});

