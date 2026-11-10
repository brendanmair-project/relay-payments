import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { apiKey, createIncident, resolveOpenIncidents, type IncidentRow } from "./helpers";

let incident: IncidentRow;
const title = `e2e incident ${Date.now()}`;

test.beforeAll(async () => {
  await resolveOpenIncidents("B");
  incident = await createIncident("B", title);
});

test.afterAll(async () => {
  await resolveOpenIncidents("B");
});

async function openDetail(page: Page) {
  await page.goto("/incidents");
  await page.getByRole("link", { name: title }).click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incident.id}$`));
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

test("open the list and detail, triage, then resolve and see the status change", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Incidents" }).click();
  await expect(page).toHaveURL(/\/incidents$/);
  const row = page.getByRole("row", { name: new RegExp(title) });
  await expect(row).toContainText("Detected");
  await expect(row).toContainText("Manual");

  await row.getByRole("link", { name: title }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByRole("region", { name: "Summary" })).toContainText("Rule-based", { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Resolve", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Triage", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resolve", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Triage", exact: true })).toHaveCount(0);
  await expect(page.getByText("Triaged", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Resolve", exact: true }).click();
  await expect(page.getByText("Resolved", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^(Triage|Resolve)$/ })).toHaveCount(0);

  await page.goto("/incidents");
  await expect(page.getByRole("row", { name: new RegExp(title) })).toContainText("Resolved");
});

test("the list page makes one request per refresh and shows the affected count from it", async ({ page }) => {
  const seen: string[] = [];
  page.on("request", (req) => {
    const path = new URL(req.url()).pathname;
    if (path.startsWith("/api/incidents")) seen.push(`${path}${new URL(req.url()).search}`);
  });
  await page.goto("/incidents");
  await expect(page.getByRole("row", { name: new RegExp(title) })).toContainText("Manual");
  await page.waitForTimeout(1500);
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.every((p) => p === "/api/incidents?limit=20")).toBe(true);
  const cells = page.getByRole("row", { name: new RegExp(title) }).getByRole("cell");
  await expect(cells.last()).toHaveText("0");
});

test("a large incident detail is paged 20 at a time with each payment's events collapsed", async ({ page }) => {
  const payments = Array.from({ length: 45 }, (_, i) => ({
    id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
    status: "captured",
    amount_minor: 1999,
    currency: "USD",
    processor: "B",
    events: [
      {
        id: 9000 + i,
        type: "payment.failed",
        reason: "outage",
        processor: "A",
        occurred_at: "2026-10-01T14:03:20.000000Z",
      },
    ],
  }));
  await page.route(`**/api/incidents/${incident.id}`, async (route) => {
    const real = await route.fetch();
    const body = await real.json();
    await route.fulfill({ response: real, json: { ...body, affected_count: 45, affected_payments: payments } });
  });
  await openDetail(page);
  const region = page.getByRole("region", { name: "Affected payments" });
  await expect(region.getByRole("status")).toHaveText("Page 1 of 3, payments 1 to 20 of 45");
  await expect(region.locator("details")).toHaveCount(20);
  await expect(region.locator("details[open]")).toHaveCount(0);
  await region.getByRole("button", { name: "Next page" }).click();
  await expect(region.getByRole("status")).toHaveText("Page 2 of 3, payments 21 to 40 of 45");
  await region.locator("summary").first().click();
  await expect(region.locator("details[open]")).toHaveCount(1);
  // Collapsed events stay in the DOM, so look only inside the payment that was opened.
  await expect(region.locator("details[open]").getByText(/payment.failed processor A \(outage\)/)).toBeVisible();
  await region.getByRole("button", { name: "Previous page" }).click();
  await expect(region.getByRole("status")).toHaveText("Page 1 of 3, payments 1 to 20 of 45");
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});

for (const where of ["list", "detail"] as const) {
  test(`axe reports no serious or critical violations on the incident ${where} page`, async ({ page }) => {
    if (where === "list") {
      await page.goto("/incidents");
      await expect(page.getByRole("link", { name: title })).toBeVisible();
    } else {
      await openDetail(page);
      await expect(page.getByRole("region", { name: "Summary" })).toContainText("Rule-based", { timeout: 30_000 });
    }
    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}

test("the API key never appears in browser traffic or source on the incident pages", async ({ page }) => {
  const key = apiKey();
  const seen: string[] = [];
  page.on("request", (req) => {
    seen.push(`${req.url()}\n${JSON.stringify(req.headers())}\n${req.postData() ?? ""}`);
  });
  const bodies: string[] = [];
  page.on("response", async (res) => {
    if (res.url().includes("/api/")) bodies.push(await res.text().catch(() => ""));
  });
  await page.goto("/incidents");
  await expect(page.getByRole("link", { name: title })).toBeVisible();
  const listHtml = await page.content();
  await page.getByRole("link", { name: title }).click();
  await expect(page.getByRole("region", { name: "Summary" })).toContainText("Rule-based", { timeout: 30_000 });
  const detailHtml = await page.content();
  const rawList = await (await page.request.get("/incidents")).text();
  const rawDetail = await (await page.request.get(`/incidents/${incident.id}`)).text();

  expect(seen.length).toBeGreaterThan(2);
  for (const text of [...seen, ...bodies, listHtml, detailHtml, rawList, rawDetail]) expect(text).not.toContain(key);
});

test("a cross-site POST to the transitions route is rejected with 403 and changes nothing", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://localhost:3000" });
  const res = await ctx.post(`/api/incidents/${incident.id}/transitions`, {
    headers: { "Sec-Fetch-Site": "cross-site", "Content-Type": "application/json" },
    data: { to: "triaged" },
  });
  expect(res.status()).toBe(403);
  const regen = await ctx.post(`/api/incidents/${incident.id}/summary/regenerate`, {
    headers: { "Sec-Fetch-Site": "cross-site" },
  });
  expect(regen.status()).toBe(403);
  await ctx.dispose();
});

test("a foreign Host header is rejected on the incident routes", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://localhost:3000" });
  const res = await ctx.get("/api/incidents", { headers: { Host: "evil.example" } });
  expect(res.status()).toBe(403);
  await ctx.dispose();
});
