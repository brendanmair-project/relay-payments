import { expect, test, type Page } from "@playwright/test";

import { apiKey, restoreProfiles, SIM } from "./helpers";

// REL-66: the one-click outage story, end to end against docker compose with the model unreachable (OLLAMA_URL points
// nowhere, so every explanation is the rules text). The full run takes about two minutes: 25 payments, the outage, a
// drain, the switch back and the router's health window.
const headers = () => ({ "X-API-Key": apiKey() });

async function outageOnA(): Promise<boolean> {
  const res = await fetch(`${SIM}/control/processors`, { headers: headers() });
  return ((await res.json()) as { processors: { a: { outage: boolean } } }).processors.a.outage;
}

async function settle(): Promise<void> {
  // A run left over from an earlier attempt must not block this one.
  await fetch(`${SIM}/control/story/run`, { method: "DELETE", headers: headers() });
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const { state } = (await (await fetch(`${SIM}/control/story/run`, { headers: headers() })).json()) as {
      state: string;
    };
    if (state !== "running" && state !== "stopping") return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("a story run did not end");
}

// Every caption the page shows, in order, whatever the polling speed: the observer sees each committed change.
async function recordCaptions(page: Page): Promise<void> {
  await page.evaluate(() => {
    const el = document.querySelector('[aria-label="Story step"]')!;
    const seen: string[] = [];
    const push = () => {
      const text = (el.textContent ?? "").trim();
      if (text && seen.at(-1) !== text) seen.push(text);
    };
    new MutationObserver(push).observe(el, { childList: true, characterData: true, subtree: true });
    (window as unknown as { __captions: string[] }).__captions = seen;
  });
}

const captions = (page: Page) => page.evaluate(() => (window as unknown as { __captions: string[] }).__captions);

test.beforeAll(async () => {
  await restoreProfiles();
  await settle();
});
test.afterEach(async () => {
  await settle();
  expect(await outageOnA()).toBe(false);
});

test("Stop ends the run and leaves Processor A outage off", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  const story = page.getByRole("region", { name: "Outage story" });
  const step = story.getByRole("status", { name: "Story step" });
  await story.getByRole("button", { name: "Run the outage demo" }).click();
  await expect(step).toHaveText("Payments flowing");
  await expect(story.getByRole("button", { name: "Run the outage demo" })).toBeDisabled();
  // A second start while one runs is refused by the simulator.
  const second = await fetch(`${SIM}/control/story/run`, { method: "POST", headers: headers() });
  expect(second.status).toBe(409);
  await story.getByRole("button", { name: "Stop the demo" }).click();
  await expect(step).toHaveText("Demo stopped", { timeout: 60_000 });
  await expect(story.getByRole("button", { name: "Stop the demo" })).toHaveCount(0);
  await expect(story.getByRole("button", { name: "Run the outage demo" })).toBeEnabled();
});

test("one click runs the outage story and ends on Money recovered", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/");
  const story = page.getByRole("region", { name: "Outage story" });
  const step = story.getByRole("status", { name: "Story step" });
  await recordCaptions(page);
  await story.getByRole("button", { name: "Run the outage demo" }).click();
  // The manual toggle steps aside while the run controls the outage.
  await expect(page.getByRole("button", { name: "Start Processor A outage" })).toBeDisabled();
  await expect(step).toHaveText("Money recovered", { timeout: 280_000 });
  const seen = await captions(page);
  const at = (text: string) => seen.indexOf(text);
  expect(at("Payments flowing")).toBeGreaterThanOrEqual(0);
  expect(at("Processor A failing")).toBeGreaterThan(at("Payments flowing"));
  expect(at("Money recovered")).toBeGreaterThan(at("Processor A failing"));
  await expect(story.getByText("Revenue recovered")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start Processor A outage" })).toBeEnabled();
  await expect(story.getByRole("button", { name: "Run the outage demo" })).toBeEnabled();
  expect(await outageOnA()).toBe(false);
});
