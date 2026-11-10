import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AnalyticsPage from "./page";

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

describe("AnalyticsPage", () => {
  it("names the product, links back to the payments and the incidents and shows the analytics", () => {
    render(<AnalyticsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Relay" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All payments" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Incidents" })).toHaveAttribute("href", "/incidents");
    expect(screen.getByRole("heading", { level: 2, name: "Analytics" })).toBeInTheDocument();
  });
});
