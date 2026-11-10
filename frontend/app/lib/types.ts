export type Payment = {
  id: string;
  amount_minor: number;
  currency: string;
  description: string | null;
  reference: string | null;
  status: string;
  display_status: string;
  attempt_no: number;
  is_final: boolean;
  processor: string | null;
  created_at: string;
  status_changed_at: string;
  final_at: string | null;
};

export type PaymentEvent = {
  seq: number;
  type: string;
  attempt_no: number;
  from_status: string | null;
  to_status: string | null;
  processor: string | null;
  reason: string | null;
  data: Record<string, unknown>;
  occurred_at: string;
};

export type PaymentDetailData = Payment & { events: PaymentEvent[] };

export type Explanation = {
  payment_id: string;
  source: "model" | "rules";
  model: string | null;
  text: string;
  cited_event_seqs: number[];
  trigger: string;
  generated_at: string;
  fallback_reason: string | null;
};

export type ProcessorHealth = {
  strategy: string;
  window_seconds: number;
  error_threshold: number;
  processors: { name: string; attempts: number; errors: number; error_rate: number; state: string }[];
  computed_at: string;
};

export type Incident = {
  id: string;
  processor: string | null;
  source: "rule" | "manual";
  status: "detected" | "triaged" | "resolved";
  title: string;
  opened_at: string;
  opened_by_event_id: number | null;
  recovered_at: string | null;
  triaged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  affected_count: number;
};

export type IncidentEvent = {
  id: number;
  type: string;
  reason: string | null;
  processor: string | null;
  occurred_at: string;
};

export type AffectedPayment = {
  id: string;
  status: string;
  amount_minor: number;
  currency: string;
  processor: string | null;
  events: IncidentEvent[];
};

export type IncidentDetailData = Incident & { affected_payments: AffectedPayment[] };

export type IncidentSummary = {
  incident_id: string;
  source: "model" | "rules";
  model: string | null;
  text: string;
  cited_event_ids: number[];
  cause: string;
  trigger: string;
  generated_at: string;
  fallback_reason: string | null;
};

export type Percentiles = { count: number; p50_ms: number | null; p95_ms: number | null; p99_ms?: number | null };

export type ProcessorFigures = {
  volume: number;
  captured: number;
  failed: number;
  declined: number;
  success_rate: number | null;
  latency: Percentiles;
  call_latency: Percentiles;
  failure_reasons: Record<string, number>;
};

export type RescuePath = { count: number; amount_minor_by_currency: Record<string, number> };

export type ExplanationTiming =
  | { available: false; note: string }
  | {
      available: true;
      sources: Record<string, Percentiles>;
      all: Percentiles;
      fallback_rate: number | null;
      fallback_reasons: Record<string, number>;
      fallback_cause_mismatch: number;
      fallback_model_failures: number;
      backlog_max: number;
      backlog_end: number;
    };

export type AnalyticsData = {
  window: { from: string; to: string; processor: string | null };
  volume: { payments: number; final: number };
  latency: Percentiles;
  processors: Record<string, ProcessorFigures>;
  revenue_recovered_by_rescue_path: Record<string, RescuePath>;
  time_to_explanation: ExplanationTiming;
};

export type BaselineData =
  | { available: false }
  | {
      available: true;
      label: string;
      synthetic: boolean;
      scenario: string;
      seed: number;
      run: number;
      run_date: string | null;
      baseline_description: string;
      success_rate_static_pct: number;
      success_rate_relay_pct: number;
      uplift_pp: number;
      revenue_recovered: Record<string, number>;
      revenue_by_rescue_path: Record<string, Record<string, number>>;
    };
