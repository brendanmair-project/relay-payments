// REL-65: screenshots of the redesigned console at 1280 px and phone width during a scripted Processor A outage, for
// the owner's approval. The browser's /api requests are answered with committed fixtures (tests/fixtures), so the
// shots need no docker stack: the page, its components and its states are the real build; the figures are synthetic
// fixture values, not a measured run. Rerun from the frontend folder after `npm run build`:
//   npx playwright test --config tests/screenshots/playwright.config.ts
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { agreedExplanation, agreedPayment } from "../fixtures/explanations";
import { analyticsData, baselineData } from "../fixtures/analytics";
import { detected, rulesSummary } from "../fixtures/incidents";
import { healthDuringOutage, healthNormal, outagePayments } from "../fixtures/console";
import type { AnalyticsData, Payment } from "../../app/lib/types";

const OUT = __dirname;
const ok = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

// Illustrative synthetic figures for the headline, large enough to read as a story. Not a measured run.
const analytics: AnalyticsData = {
  ...analyticsData,
  money_saved: {
    ...analyticsData.money_saved,
    payments_rescued: {
      count: 92,
      by_rescue_path: {
        failover: { count: 33, amount_minor_by_currency: { USD: 2_912_040, EUR: 1_120_033 } },
        retry: { count: 59, amount_minor_by_currency: { USD: 4_420_061, GBP: 1_618_218 } },
      },
    },
    revenue_recovered: {
      ...analyticsData.money_saved.revenue_recovered,
      amount_minor_by_currency: { EUR: 1_120_033, GBP: 1_618_218, USD: 7_332_101 },
    },
    investigation_time_saved: {
      ...analyticsData.money_saved.investigation_time_saved,
      explained_failures: 34,
      seconds_saved: 244_800,
    },
  },
};

const payments: Payment[] = [
  ...outagePayments,
  ...outagePayments.map((p, i) => ({ ...p, id: `1000000${i}-0000-4000-8000-00000000001${i}` })),
  { ...(agreedPayment as unknown as Payment), events: undefined } as unknown as Payment,
];

async function script(page: Page): Promise<void> {
  let outage = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/demo/state") return ok(route, { processors: { a: { outage }, b: { outage: false } } });
    if (path === "/api/demo/outage") {
      outage = (route.request().postDataJSON() as { enabled: boolean }).enabled;
      return ok(route, { processors: { a: { outage }, b: { outage: false } } });
    }
    if (path === "/api/processors/health") return ok(route, outage ? healthDuringOutage : healthNormal);
    if (path === "/api/analytics/baseline") return ok(route, baselineData);
    if (path === "/api/analytics") return ok(route, analytics);
    if (path === "/api/payments") return ok(route, { items: payments });
    if (path.endsWith("/explanation")) return ok(route, agreedExplanation);
    if (path === "/api/incidents") return ok(route, { items: outage ? [detected] : [] });
    if (path.endsWith("/summary")) return ok(route, rulesSummary);
    return route.fulfill({ status: 404, body: "{}" });
  });
}

for (const [name, size] of [
  ["1280", { width: 1280, height: 800 }],
  ["390-phone", { width: 390, height: 844 }],
] as const) {
  test(`console during a scripted Processor A outage at ${name}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(size);
    await script(page);
    await page.goto("/");
    await expect(page.getByRole("group", { name: "Revenue recovered" })).toBeVisible();
    await expect(page.getByRole("status", { name: "Failover state" })).toContainText("No failover");

    // The scripted outage: the viewer clicks the control, the router starts avoiding Processor A.
    await page.getByRole("button", { name: "Start Processor A outage" }).click();
    await expect(page.getByText("Processor A outage: Active")).toBeVisible();
    await expect(page.getByRole("status", { name: "Failover state" })).toContainText("Failover active", {
      timeout: 15_000,
    });
    await expect(page.getByRole("region", { name: "Open incident" })).toContainText(rulesSummary.text, {
      timeout: 15_000,
    });
    await expect(page.getByRole("region", { name: "One failure, explained" })).toContainText(agreedExplanation.text);
    // The outage state is the busiest one: axe must find nothing serious or critical (contrast included).
    const { violations } = await new AxeBuilder({ page }).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(OUT, `console-outage-${name}.png`), fullPage: true });
  });
}
