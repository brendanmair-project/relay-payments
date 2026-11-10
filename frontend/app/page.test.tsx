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
});
