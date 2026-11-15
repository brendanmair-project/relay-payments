import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { createPayment, restoreProfiles, waitForFinal } from "./helpers";

// REL-65: the redesigned console leads with value, then the AI, then the dense console (ADR-0018). A short seeded
// run gives the page real figures; the cases that need a degraded processor are covered by the Vitest component tests.
test.beforeAll(async () => {
  await restoreProfiles();
  const ids = [await createPayment(), await createPayment(), await createPayment()];
  for (const id of ids) await waitForFinal(id);
});

test("the home page leads with the money-saved headline, then the AI section, then the console", async ({ page }) => {
  await page.goto("/");
  const band = page.getByRole("region", { name: "Money saved" });
  await expect(band.getByRole("group", { name: "Revenue recovered" })).toBeVisible();
  await expect(band.getByRole("group", { name: "Payments rescued" })).toBeVisible();
  await expect(band.getByRole("group", { name: "Investigation time saved" })).toContainText(
    "estimated against the 2-hour manual baseline",
  );
  await expect(band).toContainText("Synthetic data");

  const headings = await page.getByRole("heading", { level: 2 }).allTextContents();
  const at = (text: string) => headings.findIndex((h) => h.includes(text));
  expect(at("Money saved")).toBeGreaterThanOrEqual(0);
  expect(at("How the AI explains failures")).toBeGreaterThan(at("Money saved"));
  expect(at("Processor health")).toBeGreaterThan(at("How the AI explains failures"));
  expect(at("Latest payments")).toBeGreaterThan(at("Processor health"));
  await expect(page.getByRole("region", { name: "Processor health" }).getByRole("status")).toContainText(/failover/i);
});

for (const [label, size] of [
  ["desktop", { width: 1280, height: 800 }],
  ["phone", { width: 390, height: 844 }],
] as const) {
  test(`axe reports no serious or critical violations on the home page at ${label} width`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto("/");
    await expect(page.getByRole("group", { name: "Revenue recovered" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Processor health" }).getByRole("status")).toBeVisible();
    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}

test("the phone layout has no horizontal page scroll and the page does not animate under reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("group", { name: "Revenue recovered" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const durations = await page.evaluate(() =>
    [...document.querySelectorAll("button")].map((b) => getComputedStyle(b).transitionDuration),
  );
  for (const d of durations) expect(d).toBe("0s");
});
