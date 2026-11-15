// REL-65: the console screenshots. Separate from the e2e config so CI never runs them; it serves the production build
// (`npm run build` first) and the capture answers the browser's /api requests with fixtures, so no stack is needed.
//   npx playwright test --config tests/screenshots/playwright.config.ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.capture.ts",
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://localhost:3000" },
  webServer: { command: "npm run start", cwd: "../..", url: "http://localhost:3000", reuseExistingServer: true },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
