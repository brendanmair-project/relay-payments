import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Home", () => {
  it("names the product and says the data is synthetic", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 1, name: "Relay" })).toBeInTheDocument();
    expect(screen.getByText(/synthetic data only/i)).toBeInTheDocument();
  });

  it("links to the analytics page next to Incidents", () => {
    render(<Home />);
    expect(screen.getByRole("link", { name: "Analytics" })).toHaveAttribute("href", "/analytics");
    expect(screen.getByRole("link", { name: "Incidents" })).toHaveAttribute("href", "/incidents");
  });

  it("shows the payments list", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 2, name: /latest payments/i })).toBeInTheDocument();
  });

  it("leads with value, then the AI, then the console (ADR-0018)", () => {
    render(<Home />);
    const names = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    const order = [
      "Money saved",
      "How the AI explains failures",
      "Processor health",
      "Open incident",
      "Latest payments",
    ];
    const positions = order.map((o) => names.findIndex((n) => n?.toLowerCase().includes(o.toLowerCase())));
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it("keeps the outage control in the header area, before the value story", () => {
    render(<Home />);
    const control = screen.getByRole("region", { name: "Demo controls" });
    const band = screen.getByRole("region", { name: "Money saved" });
    expect(control.compareDocumentPosition(band) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has one main landmark and a skip link to it", () => {
    render(<Home />);
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Skip to the payments console" })).toHaveAttribute("href", "#console");
  });
});
