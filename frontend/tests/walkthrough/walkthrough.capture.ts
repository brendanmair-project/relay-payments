// REL-61: records the README walkthrough screenshots on the local stack during a scripted Processor A outage.
// Not part of the CI e2e run: it has its own config (playwright.walkthrough.config.ts), its own file suffix and no
// place in the `e2e` script. Rerun with the stack up and RELAY_API_KEY set in the shell:
//   npm --prefix frontend run walkthrough
// All data is synthetic. Pages are served by the frontend, whose server routes hold the key, so no key is on screen.
import { randomUUID } from "node:crypto";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, SIM, apiKey, restoreProfiles, waitForFinal } from "../e2e/helpers";

const OUT = join(__dirname, "..", "..", "..", "docs", "images", "walkthrough");
const keyHeader = () => ({ "X-API-Key": apiKey() });

async function setOutage(enabled: boolean): Promise<void> {
  const res = await fetch(`${SIM}/control/processors/a/outage`, {
    method: "POST",
    headers: { ...keyHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`outage ${enabled}: ${res.status}`);
}

const CURRENCIES = ["USD", "EUR", "GBP"] as const;

async function createPayment(index: number): Promise<string> {
  const res = await fetch(`${API}/payments`, {
    method: "POST",
    headers: { ...keyHeader(), "Idempotency-Key": randomUUID(), "Content-Type": "application/json" },
    body: JSON.stringify({
      amount_minor: 1500 + ((index * 937) % 18000),
      currency: CURRENCIES[index % CURRENCIES.length],
      description: `walkthrough order ${index}`,
      reference: `walkthrough-${Date.now()}-${index}`,
    }),
  });
  if (res.status !== 201) throw new Error(`create payment: ${res.status}`);
  return ((await res.json()) as { id: string }).id;
}

type Ev = { type: string; reason: string | null; processor: string | null };

async function failedOverId(ids: string[]): Promise<string | null> {
  for (const id of ids) {
    const res = await fetch(`${API}/payments/${id}`, { headers: keyHeader() });
    const events = ((await res.json()) as { events: Ev[] }).events;
    const lower = (v: string | null) => (v ?? "").toLowerCase();
    const failedOnA = events.some((e) => e.type === "payment.failed" && lower(e.processor) === "a");
    const routedToB = events.some((e) => e.type === "payment.routed" && lower(e.processor) === "b");
    if (failedOnA && routedToB) return id;
  }
  return null;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
}

test("record the outage walkthrough", async ({ page }) => {
  test.setTimeout(240_000);
  await restoreProfiles();
  await setOutage(false);
  await setOutage(true);
  const ids: string[] = [];
  try {
    for (let i = 0; i < 14; i++) {
      const id = await createPayment(i);
      await waitForFinal(id);
      ids.push(id);
    }

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("link", { name: ids[ids.length - 1] })).toBeVisible();
    await expect(page.getByText("Processor A outage: Active")).toBeVisible();
    await shot(page, "01-payments-list-mid-outage");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByRole("link", { name: ids[ids.length - 1] })).toBeVisible();
    await shot(page, "02-payments-list-phone");

    await page.setViewportSize({ width: 1280, height: 900 });
    const failover = await failedOverId(ids);
    expect(failover, "a payment that failed on A and was routed to B").not.toBeNull();
    await page.goto(`/payments/${failover}`);
    await expect(page.getByRole("list", { name: "Payment timeline" })).toContainText("payment.routed");
    // The explanation appears within a few seconds (model or rules text); keep going if it is slow.
    await expect(page.getByRole("region", { name: "Explanation" }))
      .not.toContainText("Generating", { timeout: 30_000 })
      .catch(() => undefined);
    await shot(page, "03-payment-timeline-failover");

    const health = page.getByRole("region", { name: "Processor health" });
    await expect(health).toContainText(/avoided/i);
    await health.screenshot({ path: `${OUT}/04-processor-health-a-avoided.png` });
  } finally {
    await setOutage(false);
  }

  // After the outage: the analytics view and the incident the outage opened.
  for (let i = 100; i < 112; i++) await waitForFinal(await createPayment(i));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot(page, "05-analytics-after-outage");

  await page.goto("/incidents");
  await page.waitForLoadState("networkidle");
  await shot(page, "06-incidents-after-outage");
  await restoreProfiles();
});
