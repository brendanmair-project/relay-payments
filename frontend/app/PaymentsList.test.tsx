import { cleanup, act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PaymentsList from "./PaymentsList";
import type { Payment } from "./lib/types";

const mk = (over: Partial<Payment>): Payment => ({
  id: "5f0e6c52-3f3b-4b2e-9a51-7a4f2c9d1e10",
  amount_minor: 1999,
  currency: "USD",
  description: null,
  reference: null,
  status: "captured",
  display_status: "Captured",
  attempt_no: 1,
  is_final: true,
  processor: "A",
  created_at: "2026-10-01T14:03:22.418Z",
  status_changed_at: "2026-10-01T14:03:23.000Z",
  final_at: "2026-10-01T14:03:23.000Z",
  ...over,
});

const fetchMock = vi.fn();
const ok = (items: Payment[]) =>
  new Response(JSON.stringify({ items, next_cursor: null }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

async function flush() {
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

describe("PaymentsList", () => {
  it("shows a loading message first", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    render(<PaymentsList />);
    expect(screen.getByText(/loading payments/i)).toBeInTheDocument();
  });

  it("fetches only the frontend's own /api/payments route", async () => {
    fetchMock.mockResolvedValue(ok([]));
    render(<PaymentsList />);
    await flush();
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/^\/api\/payments\?limit=20$/);
  });

  it("renders status, processor, formatted amount and time for each payment", async () => {
    fetchMock.mockResolvedValue(
      ok([mk({}), mk({ id: "a-2", currency: "JPY", display_status: "Declined", status: "declined", processor: "B" })]),
    );
    render(<PaymentsList />);
    await flush();
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("$19.99")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Captured")).toBeInTheDocument();
    expect(within(rows[1]).getByText("A")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2026-10-01 14:03:23Z")).toBeInTheDocument();
    expect(within(rows[2]).getByText("¥1,999")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Declined")).toBeInTheDocument();
    expect(within(rows[2]).getByText("B")).toBeInTheDocument();
  });

  it("shows a non-final failed payment as Retrying, in text", async () => {
    fetchMock.mockResolvedValue(
      ok([mk({ status: "failed", is_final: false, display_status: "Retrying", attempt_no: 1 })]),
    );
    render(<PaymentsList />);
    await flush();
    expect(screen.getByText("Retrying")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("shows a dash for the processor before routing", async () => {
    fetchMock.mockResolvedValue(
      ok([mk({ status: "received", display_status: "Received", processor: null, attempt_no: 0, is_final: false })]),
    );
    render(<PaymentsList />);
    await flush();
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Received")).toBeInTheDocument();
    expect(within(row).getByLabelText("not routed yet")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    fetchMock.mockResolvedValue(ok([]));
    render(<PaymentsList />);
    await flush();
    expect(screen.getByText(/no payments yet/i)).toBeInTheDocument();
  });

  it("shows an error state with no rows when the first load fails", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 503 }));
    render(<PaymentsList />);
    await flush();
    expect(screen.getByText(/could not load payments/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/error/i);
  });

  it("refreshes every 5 seconds and shows when it last updated", async () => {
    fetchMock.mockResolvedValueOnce(ok([mk({})]));
    fetchMock.mockResolvedValue(
      ok([mk({}), mk({ id: "a-2", display_status: "Processing", status: "routed", is_final: false })]),
    );
    vi.setSystemTime(new Date("2026-10-01T14:10:00Z"));
    render(<PaymentsList />);
    await flush();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("status")).toHaveTextContent("Last updated: 14:10:00Z");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("Last updated: 14:10:05Z");
  });

  it("keeps the last rows and shows the error when a refresh fails", async () => {
    fetchMock.mockResolvedValueOnce(ok([mk({})]));
    fetchMock.mockRejectedValue(new TypeError("network"));
    render(<PaymentsList />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText("$19.99")).toBeInTheDocument();
    expect(screen.getByText(/could not load payments/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/error/i);
  });

  it("stops polling when unmounted", async () => {
    fetchMock.mockResolvedValue(ok([]));
    const { unmount } = render(<PaymentsList />);
    await flush();
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
