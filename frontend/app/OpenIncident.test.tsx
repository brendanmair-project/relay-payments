import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OpenIncident from "./OpenIncident";
import { INCIDENT_ID, detected, resolved, rulesSummary } from "../tests/fixtures/incidents";
import type { Incident } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function show(items: Incident[], summary: Response | unknown = rulesSummary, list?: Response) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/incidents?")) return list ?? json({ items });
    if (url.endsWith("/summary")) return summary instanceof Response ? summary : json(summary);
    throw new Error(`unexpected ${url}`);
  });
  render(<OpenIncident />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("OpenIncident", () => {
  it("shows the open incident with a text status, its times and the AI summary with its source", async () => {
    await show([resolved, detected]);
    const region = screen.getByRole("region", { name: "Open incident" });
    expect(region).toHaveTextContent("Processor A is failing payments");
    expect(region).toHaveTextContent("Detected");
    expect(region).toHaveTextContent("1 payment affected");
    expect(region).toHaveTextContent(rulesSummary.text);
    expect(region).toHaveTextContent("AI summary (rule-based)");
    expect(screen.getByRole("link", { name: /Processor A is failing payments/ })).toHaveAttribute(
      "href",
      `/incidents/${INCIDENT_ID}`,
    );
    expect(fetchMock).toHaveBeenCalledWith(`/api/incidents/${INCIDENT_ID}/summary`, expect.anything());
  });

  it("labels a model-written summary with the model name", async () => {
    await show([detected], { ...rulesSummary, source: "model", model: "granite3.3:2b", fallback_reason: null });
    expect(screen.getByRole("region", { name: "Open incident" })).toHaveTextContent(
      "AI summary (model: granite3.3:2b)",
    );
  });

  it("says there is no open incident when all are resolved", async () => {
    await show([resolved]);
    expect(screen.getByRole("region", { name: "Open incident" })).toHaveTextContent("No open incident");
    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/summary"))).toBe(false);
  });

  it("says when the summary could not be loaded but keeps the incident visible", async () => {
    await show([detected], json({}, 500));
    const region = screen.getByRole("region", { name: "Open incident" });
    expect(region).toHaveTextContent("Processor A is failing payments");
    expect(region).toHaveTextContent("Could not load the AI summary");
  });

  it("says when the incidents could not be loaded", async () => {
    await show([], undefined, json({}, 500));
    expect(screen.getByRole("region", { name: "Open incident" })).toHaveTextContent("Could not load incidents");
  });
});
