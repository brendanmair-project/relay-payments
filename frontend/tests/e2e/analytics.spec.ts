import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { API, apiKey, createPayment, restoreProfiles, waitForFinal } from "./helpers";

// A short seeded run: three payments through the real stack, so the page has figures to show.
test.beforeAll(async () => {
  await restoreProfiles();
  const ids = [await createPayment(), await createPayment(), await createPayment()];
  for (const id of ids) await waitForFinal(id);
});

test("the analytics page loads with figures, the filters and the baseline section", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  await expect(page.getByRole("heading", { level: 2, name: "Analytics" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(/^\d+ payments$/);
  const table = page.getByRole("table", { name: "Figures by processor" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Processor A" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Processor B" })).toBeVisible();
  await expect(table.getByRole("row", { name: /^Payments routed/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "Revenue recovered by rescue path", exact: true })).toBeVisible();

  const baseline = page.getByRole("region", { name: "Against the static-routing baseline" });
  await expect(baseline).toContainText("Synthetic data; baseline is static routing.");
  await expect(baseline).toContainText("seed 7");

  await page.getByRole("combobox", { name: "Processor" }).selectOption("B");
  await expect(table.getByRole("columnheader", { name: "Processor A" })).toHaveCount(0);
  await expect(table.getByRole("columnheader", { name: "Processor B" })).toBeVisible();
  await page.getByRole("combobox", { name: "Range" }).selectOption("1h");
  await expect(page.getByRole("status")).toHaveText(/^\d+ payments$/);
});

test("axe reports no serious or critical violations on the analytics page", async ({ page }) => {
  await page.goto("/analytics");
  await expect(page.getByRole("table", { name: "Figures by processor" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Against the static-routing baseline" })).toContainText("seed");
  const { violations } = await new AxeBuilder({ page }).analyze();
  const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test("the API key never appears in browser traffic or source on the analytics page", async ({ page }) => {
  const key = apiKey();
  const seen: string[] = [];
  page.on("request", (req) => {
    seen.push(`${req.url()}\n${JSON.stringify(req.headers())}\n${req.postData() ?? ""}`);
  });
  const bodies: string[] = [];
  page.on("response", async (res) => {
    if (res.url().includes("/api/")) bodies.push(await res.text().catch(() => ""));
  });
  await page.goto("/analytics");
  await expect(page.getByRole("table", { name: "Figures by processor" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Against the static-routing baseline" })).toContainText("seed");
  const html = await page.content();
  const rawAnalytics = await (await page.request.get("/api/analytics")).text();
  const rawBaseline = await (await page.request.get("/api/analytics/baseline")).text();

  expect(seen.some((s) => s.includes("/api/analytics"))).toBe(true);
  expect(bodies.length).toBeGreaterThan(1);
  for (const text of [...seen, ...bodies, html, rawAnalytics, rawBaseline]) expect(text).not.toContain(key);
});

test("the api itself refuses analytics without the key, and a foreign Host is refused on the route", async ({
  playwright,
  request,
}) => {
  const direct = await request.get(`${API}/analytics`);
  expect(direct.status()).toBe(401);
  const ctx = await playwright.request.newContext({ baseURL: "http://localhost:3000" });
  const res = await ctx.get("/api/analytics", { headers: { Host: "evil.example" } });
  expect(res.status()).toBe(403);
  await ctx.dispose();
});
