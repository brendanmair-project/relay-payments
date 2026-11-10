import { describe, expect, it } from "vitest";

import { formatAmount, formatTime, reasonText, statusLabel } from "./format";
import type { Payment } from "./types";

describe("formatAmount", () => {
  it.each([
    [1999, "USD", "$19.99"],
    [1999, "EUR", "€19.99"],
    [1999, "GBP", "£19.99"],
    [1999, "JPY", "¥1,999"],
    [5, "USD", "$0.05"],
    [100, "USD", "$1.00"],
    [1_000_000_000_000, "USD", "$10,000,000,000.00"],
    [1_000_000_000_000, "JPY", "¥1,000,000,000,000"],
  ])("formats %i minor units of %s as %s", (minor, currency, expected) => {
    expect(formatAmount(minor, currency)).toBe(expected);
  });

  it("never rounds through floating point", () => {
    expect(formatAmount(999_999_999_999, "USD")).toBe("$9,999,999,999.99");
  });

  it("shows the raw minor units when the currency is unknown", () => {
    expect(formatAmount(1999, "XXZ9")).toBe("1999 XXZ9 (minor units)");
  });
});

describe("formatTime", () => {
  it("renders a UTC timestamp to the second", () => {
    expect(formatTime("2026-10-01T14:03:22.418Z")).toBe("2026-10-01 14:03:22Z");
  });

  it("returns a dash for a missing or invalid value", () => {
    expect(formatTime(null)).toBe("-");
    expect(formatTime("not a date")).toBe("-");
  });
});

const base: Payment = {
  id: "00000000-0000-4000-8000-000000000001",
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
};

describe("statusLabel", () => {
  it("uses the API display_status", () => {
    expect(statusLabel({ ...base, display_status: "Processing", status: "routed", is_final: false })).toBe(
      "Processing",
    );
  });

  it("labels a failed payment that is not final as Retrying", () => {
    expect(statusLabel({ ...base, status: "failed", is_final: false, display_status: "Retrying" })).toBe("Retrying");
  });

  it("keeps Failed for a final failure", () => {
    expect(statusLabel({ ...base, status: "failed", is_final: true, display_status: "Failed" })).toBe("Failed");
  });
});

describe("reasonText", () => {
  it("shows an ordinary reason in brackets and nothing without one", () => {
    expect(reasonText("payment.routed", "failover")).toBe(" (failover)");
    expect(reasonText("payment.failed", "timeout")).toBe(" (timeout)");
    expect(reasonText("payment.received", null)).toBe("");
  });

  it("says in words that adaptive routing chose the processor, so the label is text", () => {
    expect(reasonText("payment.routed", "adaptive")).toBe(" (adaptive: chosen from recent processor outcomes)");
  });
});
