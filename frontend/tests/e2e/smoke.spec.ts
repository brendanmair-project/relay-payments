import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { apiKey, createPayment, declineEverything, restoreProfiles, waitForFinal } from "./helpers";

let paymentId = "";

test.beforeAll(async () => {
  await declineEverything();
  paymentId = await createPayment();
  await waitForFinal(paymentId);
});

test.afterAll(async () => {
  await restoreProfiles();
});

async function openDetail(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: paymentId }).click();
  await expect(page).toHaveURL(new RegExp(`/payments/${paymentId}$`));
}

test("create a payment, open its detail, see timeline and explanation", async ({ page }) => {
  await openDetail(page);
  await expect(page.getByRole("heading", { name: paymentId })).toBeVisible();
  await expect(page.getByRole("list", { name: "Payment timeline" })).toContainText("payment.received");
  await expect(page.getByRole("region", { name: "Explanation" })).toContainText("Rule-based");
});

for (const where of ["list", "detail"] as const) {
  test(`axe reports no serious or critical violations on the ${where} page`, async ({ page }) => {
    if (where === "list") {
      await page.goto("/");
      await expect(page.getByRole("link", { name: paymentId })).toBeVisible();
    } else {
      await openDetail(page);
      await expect(page.getByRole("region", { name: "Explanation" })).toContainText("Rule-based");
    }
    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}

test("the API key never appears in browser requests or page source", async ({ page }) => {
  const key = apiKey();
  const seen: string[] = [];
  page.on("request", (req) => {
    seen.push(`${req.url()}\n${JSON.stringify(req.headers())}\n${req.postData() ?? ""}`);
  });
  await page.goto("/");
  await expect(page.getByRole("link", { name: paymentId })).toBeVisible();
  const listHtml = await page.content();
  await page.getByRole("link", { name: paymentId }).click();
  await expect(page.getByRole("region", { name: "Explanation" })).toContainText("Rule-based");
  const detailHtml = await page.content();
  const sourceRes = await page.request.get("/");
  const rawHtml = await sourceRes.text();

  expect(seen.length).toBeGreaterThan(2);
  for (const text of [...seen, listHtml, detailHtml, rawHtml]) expect(text).not.toContain(key);
});

test("a foreign Host header is rejected with 403", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://localhost:3000" });
  const res = await ctx.get("/api/demo/state", { headers: { Host: "evil.example" } });
  expect(res.status()).toBe(403);
  await ctx.dispose();
});

test("a cross-site POST to the outage switch is rejected with 403", async ({ playwright }) => {
  const ctx = await playwright.request.newContext({ baseURL: "http://localhost:3000" });
  const res = await ctx.post("/api/demo/outage", {
    headers: { "Sec-Fetch-Site": "cross-site", "Content-Type": "application/json" },
    data: { enabled: false },
  });
  expect(res.status()).toBe(403);
  await ctx.dispose();
});
