// Console fixtures for the home page (REL-65): shaped like the API responses of GET /processors/health and
// GET /payments (docs/architecture/api-contract.md), modelled on the mid-outage REL-62 prototype data. Synthetic only.
import type { Payment, ProcessorHealth } from "../../app/lib/types";

export const healthDuringOutage: ProcessorHealth = {
  strategy: "rules",
  window_seconds: 60,
  error_threshold: 0.5,
  processors: [
    { name: "A", attempts: 94, errors: 54, error_rate: 0.5745, state: "avoided" },
    { name: "B", attempts: 25, errors: 3, error_rate: 0.12, state: "preferred" },
  ],
  computed_at: "2026-11-10T23:46:50.000Z",
};

export const healthNormal: ProcessorHealth = {
  ...healthDuringOutage,
  processors: [
    { name: "A", attempts: 40, errors: 1, error_rate: 0.025, state: "preferred" },
    { name: "B", attempts: 12, errors: 0, error_rate: 0, state: "unknown" },
  ],
};

export const healthBothAvoided: ProcessorHealth = {
  ...healthDuringOutage,
  processors: [
    { name: "A", attempts: 94, errors: 54, error_rate: 0.5745, state: "avoided" },
    { name: "B", attempts: 20, errors: 14, error_rate: 0.7, state: "avoided" },
  ],
};

function pay(n: number, over: Partial<Payment>): Payment {
  return {
    id: `0000000${n}-0000-4000-8000-00000000000${n}`,
    amount_minor: 1500 + n * 937,
    currency: "USD",
    description: null,
    reference: null,
    status: "captured",
    display_status: "Captured",
    attempt_no: 1,
    is_final: true,
    processor: "B",
    created_at: "2026-11-10T23:46:40.000Z",
    status_changed_at: `2026-11-10T23:46:4${n}.000Z`,
    final_at: `2026-11-10T23:46:4${n}.000Z`,
    ...over,
  };
}

export const outagePayments: Payment[] = [
  pay(1, { display_status: "Retrying", status: "failed", is_final: false, processor: "A", final_at: null }),
  pay(2, { display_status: "Captured", attempt_no: 2 }),
  // Matches the agreedExplanation fixture (23.70 USD, card expired) shown as the explained failure.
  pay(3, { display_status: "Declined", status: "declined", currency: "USD", amount_minor: 2370, attempt_no: 2 }),
  pay(4, { display_status: "Captured" }),
];
