import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IncidentDetail from "./IncidentDetail";
import {
  INCIDENT_ID,
  PAYMENT_ID,
  detail,
  detected,
  manyPayments,
  resolved,
  rulesSummary,
  triaged,
} from "../tests/fixtures/incidents";
import type { Incident } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function route(incident: () => Incident, summary: unknown = rulesSummary, post?: () => Response) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") return post ? post() : json({});
    if (url.endsWith("/summary")) return json(summary);
    return json(detail(incident()));
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open() {
  render(<IncidentDetail id={INCIDENT_ID} />);
  await screen.findByRole("heading", { name: detected.title });
}

describe("IncidentDetail", () => {
  it("shows the status as text, the times, the summary, its source and fallback reason in words", async () => {
    route(() => detected);
    await open();
    expect(screen.getByText("Detected")).toBeInTheDocument();
    expect(screen.getByText(/Opened 2026-10-01 14:03:22Z/)).toBeInTheDocument();
    expect(await screen.findByText(rulesSummary.text)).toBeInTheDocument();
    expect(screen.getByText(/Rule-based/)).toBeInTheDocument();
    expect(screen.getByText(/the model could not be reached/)).toBeInTheDocument();
  });

  it.each([
    ["no_linked_events", /no failed payments were linked/],
    ["cause_mismatch", /the model's cause disagreed with the rules/],
  ])("explains the fallback reason %s in plain words", async (reason, words) => {
    route(() => detected, { ...rulesSummary, fallback_reason: reason });
    await open();
    expect(await screen.findByText(words)).toBeInTheDocument();
  });

  it("lists affected payments linking to their detail, each with its events collapsed until opened", async () => {
    route(() => detected);
    await open();
    const link = screen.getByRole("link", { name: PAYMENT_ID });
    expect(link).toHaveAttribute("href", `/payments/${PAYMENT_ID}`);
    const disclosure = screen.getByText("Events (1)").closest("details")!;
    expect(disclosure.open).toBe(false);
    expect(within(disclosure).getByText("Events (1)").tagName).toBe("SUMMARY");
    expect(screen.getByText("Events (1)")).toHaveAccessibleName(`Events of payment ${PAYMENT_ID} (1)`);
    fireEvent.click(screen.getByText("Events (1)"));
    disclosure.open = true; // jsdom does not toggle <details> on a summary click
    const events = within(disclosure).getByRole("list", { name: `Events of payment ${PAYMENT_ID}` });
    expect(within(events).getByText(/#4120 payment.failed processor A \(outage\)/)).toBeInTheDocument();
  });

  it("labels an adaptive routing event in words", async () => {
    const withAdaptive = detail(detected);
    withAdaptive.affected_payments[0].events = [
      {
        id: 4200,
        type: "payment.routed",
        reason: "adaptive",
        processor: "B",
        occurred_at: "2026-10-01T14:03:20.000000Z",
      },
    ];
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/summary") ? json(rulesSummary) : json(withAdaptive),
    );
    await open();
    expect(
      screen.getByText(/#4200 payment.routed processor B \(adaptive: chosen from recent processor outcomes\)/),
    ).toBeInTheDocument();
  });

  it("keeps every payment's events collapsed by default", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/summary") ? json(rulesSummary) : json(detail(detected, 5)),
    );
    await open();
    const all = document.querySelectorAll("section[aria-label='Affected payments'] details");
    expect(all).toHaveLength(5);
    expect([...all].some((d) => (d as HTMLDetailsElement).open)).toBe(false);
  });

  describe("paging the affected payments", () => {
    function many(count: number) {
      fetchMock.mockImplementation(async (url: string) =>
        url.endsWith("/summary")
          ? json(rulesSummary)
          : json({ ...detail(detected, 0), affected_payments: manyPayments(count) }),
      );
    }
    const shown = () => document.querySelectorAll("section[aria-label='Affected payments'] > ul > li").length;

    it("shows 20 per page with next and previous and a text status", async () => {
      many(45);
      await open();
      expect(shown()).toBe(20);
      expect(screen.getByText("Affected payments (45)")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Page 1 of 3, payments 1 to 20 of 45");
      expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      expect(screen.getByRole("status")).toHaveTextContent("Page 2 of 3, payments 21 to 40 of 45");
      expect(shown()).toBe(20);
      expect(screen.queryByRole("link", { name: PAYMENT_ID })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      expect(screen.getByRole("status")).toHaveTextContent("Page 3 of 3, payments 41 to 45 of 45");
      expect(shown()).toBe(5);
      expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
      fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
      expect(screen.getByRole("link", { name: PAYMENT_ID })).toBeInTheDocument();
    });

    it("shows no pager when everything fits on one page", async () => {
      many(20);
      await open();
      expect(shown()).toBe(20);
      expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
    });
  });

  it("says so when no payments are linked", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/summary") ? json(rulesSummary) : json(detail(detected, false)),
    );
    await open();
    expect(screen.getByText(/No payments are linked/)).toBeInTheDocument();
  });

  it("shows only Triage when detected, only Resolve when triaged, and nothing when resolved", async () => {
    for (const [incident, expected] of [
      [detected, "Triage"],
      [triaged, "Resolve"],
      [resolved, null],
    ] as const) {
      route(() => incident);
      await open();
      const names = screen.queryAllByRole("button").map((b) => b.textContent);
      expect(names.filter((n) => n === "Triage" || n === "Resolve")).toEqual(expected ? [expected] : []);
      cleanup();
    }
  });

  it("triages through the frontend route, shows a pending state, then refreshes to the new status", async () => {
    let current: Incident = detected;
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        await gate;
        current = triaged;
        return json(triaged);
      }
      return url.endsWith("/summary") ? json(rulesSummary) : json(detail(current));
    });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Triage" }));
    expect(screen.getByRole("button", { name: "Triage..." })).toBeDisabled();
    await act(async () => release());
    expect(await screen.findByText("Triaged")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(call[0]).toBe(`/api/incidents/${INCIDENT_ID}/transitions`);
    expect(JSON.parse(call[1].body)).toEqual({ to: "triaged" });
  });

  it("shows an API error in plain text and keeps the action", async () => {
    route(
      () => detected,
      rulesSummary,
      () => json({ error: { code: "invalid_incident_transition", message: "That move is not allowed." } }, 409),
    );
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Triage" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That move is not allowed.");
    expect(screen.getByRole("button", { name: "Triage" })).toBeEnabled();
  });

  it("says the incident was not found for a 404", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/summary") ? json({}, 404) : json({ error: { code: "not_found" } }, 404),
    );
    render(<IncidentDetail id="nope" />);
    expect(await screen.findByText(/Incident not found/)).toBeInTheDocument();
  });

  it("regenerates the summary through the frontend route", async () => {
    route(
      () => detected,
      rulesSummary,
      () => json({ ...rulesSummary, text: "A fresh summary.", trigger: "regenerate" }, 201),
    );
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate summary" }));
    expect(await screen.findByText("A fresh summary.")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(call[0]).toBe(`/api/incidents/${INCIDENT_ID}/summary/regenerate`);
  });
});
