// Fixtures shaped exactly like the API's incident responses (docs/architecture/api-contract.md; the response
// models in api/app/incidents/router.py). Synthetic ids and times only.
import type { AffectedPayment, Incident, IncidentDetailData, IncidentSummary } from "../../app/lib/types";

export const INCIDENT_ID = "0b6f3a52-6d0e-4c0e-8d1c-2a1f5d6e7a90";
export const PAYMENT_ID = "5f0e6c52-3f3b-4b2e-9a51-7a4f2c9d1e10";

export const detected: Incident = {
  id: INCIDENT_ID,
  processor: "A",
  source: "rule",
  status: "detected",
  title: "Processor A is failing payments",
  opened_at: "2026-10-01T14:03:22.418000Z",
  opened_by_event_id: 4121,
  recovered_at: null,
  triaged_at: null,
  resolved_at: null,
  created_at: "2026-10-01T14:03:22.500000Z",
  affected_count: 1,
};

export const triaged: Incident = { ...detected, status: "triaged", triaged_at: "2026-10-01T14:05:00.000000Z" };

export const resolved: Incident = {
  ...triaged,
  status: "resolved",
  recovered_at: "2026-10-01T14:08:10.000000Z",
  resolved_at: "2026-10-01T14:09:00.000000Z",
};

export const manual: Incident = {
  ...detected,
  id: "7c1d2e3f-0a1b-4c2d-9e3f-4a5b6c7d8e9f",
  processor: null,
  source: "manual",
  title: "Checkout slow",
  opened_by_event_id: null,
  affected_count: 0,
};

export function payment(index: number, id = PAYMENT_ID): AffectedPayment {
  return {
    id,
    status: "captured",
    amount_minor: 1999,
    currency: "USD",
    processor: "B",
    events: [
      {
        id: 4120 + index,
        type: "payment.failed",
        reason: "outage",
        processor: "A",
        occurred_at: "2026-10-01T14:03:20.000000Z",
      },
    ],
  };
}

// `count` synthetic payments with distinct ids; the first one is PAYMENT_ID.
export function manyPayments(count: number): AffectedPayment[] {
  return Array.from({ length: count }, (_, i) =>
    payment(i, i === 0 ? PAYMENT_ID : `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`),
  );
}

export function detail(incident: Incident, withPayments: boolean | number = true): IncidentDetailData {
  const count = withPayments === true ? 1 : withPayments === false ? 0 : withPayments;
  return { ...incident, affected_count: count, affected_payments: manyPayments(count) };
}

export const rulesSummary: IncidentSummary = {
  incident_id: INCIDENT_ID,
  source: "rules",
  model: null,
  text: "Processor A: 1 payment was affected. The failures were outages.",
  cited_event_ids: [4120],
  cause: "outage",
  trigger: "on_request",
  generated_at: "2026-10-01T14:04:00.000000Z",
  fallback_reason: "model_unreachable",
};
