import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LatestFailure from "./LatestFailure";
import {
  agreedExplanation,
  agreedPayment,
  disagreedExplanation,
  disagreedPayment,
} from "../tests/fixtures/explanations";
import type { Payment } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const asPayment = (p: typeof agreedPayment | typeof disagreedPayment, over: Partial<Payment> = {}) =>
  ({ ...p, events: undefined, ...over }) as unknown as Payment;

async function show(items: Payment[], explanation: Response | unknown = agreedExplanation) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/payments?")) return json({ items });
    if (url.endsWith("/explanation")) return explanation instanceof Response ? explanation : json(explanation);
    throw new Error(`unexpected ${url}`);
  });
  render(<LatestFailure />);
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

describe("LatestFailure", () => {
  it("shows the newest final failure with its explanation and the AI panel", async () => {
    await show([asPayment(disagreedPayment), asPayment(agreedPayment)]);
    const region = screen.getByRole("region", { name: "One failure, explained" });
    expect(within(region).getByRole("link", { name: agreedPayment.id })).toHaveAttribute(
      "href",
      `/payments/${agreedPayment.id}`,
    );
    expect(region).toHaveTextContent(agreedExplanation.text);
    expect(within(region).getByRole("region", { name: "How the AI explained this" })).toHaveTextContent(
      "Cross-check: agreed",
    );
    expect(fetchMock).toHaveBeenCalledWith(`/api/payments/${agreedPayment.id}/explanation`, expect.anything());
  });

  it("shows a cross-check disagreement in words when the failure had one", async () => {
    await show([asPayment(disagreedPayment, { display_status: "Declined" })], disagreedExplanation);
    expect(screen.getByRole("region", { name: "How the AI explained this" })).toHaveTextContent(
      "Cross-check: disagreed",
    );
  });

  it("says there is nothing to explain when no payment has failed", async () => {
    await show([asPayment(agreedPayment, { display_status: "Captured" })]);
    expect(screen.getByRole("region", { name: "One failure, explained" })).toHaveTextContent(
      "No failed payment to explain yet",
    );
  });

  it("says when the explanation could not be loaded", async () => {
    await show([asPayment(agreedPayment)], json({}, 500));
    expect(screen.getByRole("region", { name: "One failure, explained" })).toHaveTextContent(
      "Could not load the explanation",
    );
  });
});
