// REL-61: the README walkthrough capture. Separate from the e2e config (frontend/playwright.config.ts) so the CI e2e
// run never picks it up. With the docker compose stack up and RELAY_API_KEY set, from the repository root:
//   npx --prefix frontend playwright test --config frontend/tests/walkthrough/playwright.config.ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.capture.ts",
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://localhost:3000" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
