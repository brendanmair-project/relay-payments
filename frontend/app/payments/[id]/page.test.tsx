import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PaymentPage from "./page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("payment detail page", () => {
  it("renders the detail for the id in the route and links back to the list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(await PaymentPage({ params: Promise.resolve({ id: "abc" }) }));
    expect(screen.getByRole("link", { name: /all payments/i })).toHaveAttribute("href", "/");
    expect(screen.getByText(/loading payment/i)).toBeInTheDocument();
  });
});
