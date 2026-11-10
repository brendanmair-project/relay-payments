import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IncidentsList from "./IncidentsList";
import { detected, manual, resolved } from "../tests/fixtures/incidents";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

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

describe("IncidentsList", () => {
  it("reads only the frontend's own /api/incidents routes", async () => {
    fetchMock.mockResolvedValue(json({ items: [] }));
    render(<IncidentsList />);
    await flush();
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/incidents?limit=20");
    expect(screen.getByText(/No incidents yet/)).toBeInTheDocument();
  });

  it("shows status as text, processor, source, the three times and the affected count", async () => {
    fetchMock.mockResolvedValue(json({ items: [resolved, manual] }));
    render(<IncidentsList />);
    await flush();
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    const first = within(rows[0]);
    expect(first.getByText("Resolved")).toBeInTheDocument();
    expect(first.getByRole("link", { name: resolved.title })).toHaveAttribute("href", `/incidents/${resolved.id}`);
    expect(first.getByText("A")).toBeInTheDocument();
    expect(first.getByText("Rule")).toBeInTheDocument();
    expect(first.getByText("2026-10-01 14:03:22Z")).toBeInTheDocument();
    expect(first.getByText("2026-10-01 14:08:10Z")).toBeInTheDocument();
    expect(first.getByText("2026-10-01 14:09:00Z")).toBeInTheDocument();
    const cells = rows[0].querySelectorAll("td");
    expect(cells[cells.length - 1].textContent).toBe("1");
    expect(within(rows[1]).getByText("Manual")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Detected")).toBeInTheDocument();
    const manualCells = rows[1].querySelectorAll("td");
    expect(manualCells[manualCells.length - 1].textContent).toBe("0");
  });

  it("shows a banner and no data when the list cannot be loaded", async () => {
    fetchMock.mockResolvedValue(json({}, 500));
    render(<IncidentsList />);
    await flush();
    expect(screen.getByText(/Could not load incidents/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Error");
  });

  it("makes exactly one request per refresh, however many incidents it lists", async () => {
    fetchMock.mockResolvedValue(json({ items: [detected, resolved, manual] }));
    render(<IncidentsList intervalMs={5000} />);
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/incidents?limit=20");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([url]) => String(url).startsWith("/api/incidents?"))).toBe(true);
    const counts = within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelectorAll("td")[7].textContent);
    expect(counts).toEqual(["1", "1", "0"]);
  });
});
