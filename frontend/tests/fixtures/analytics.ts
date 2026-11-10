// Fixtures taken from real responses of the analytics code (docs/architecture/api-contract.md): `analyticsData` is
// `GET /analytics` over the five payments of api/tests/analytics/test_figures.py, `baselineData` is
// `GET /analytics/baseline` over docs/evaluation/outage-demo/results.json. Synthetic ids and times only.
import type { AnalyticsData, BaselineData } from "../../app/lib/types";

export const analyticsData: AnalyticsData = {
  window: {
    from: "2026-11-02T16:00:00.000Z",
    to: "2026-11-03T16:00:00.000Z",
    processor: null,
  },
  volume: {
    payments: 5,
    final: 5,
  },
  latency: {
    count: 5,
    p50_ms: 3000.0,
    p95_ms: 8000.0,
    p99_ms: 8000.0,
  },
  processors: {
    A: {
      volume: 4,
      captured: 1,
      failed: 2,
      declined: 1,
      success_rate: 0.3333,
      latency: {
        count: 3,
        p50_ms: 3000.0,
        p95_ms: 8000.0,
        p99_ms: 8000.0,
      },
      call_latency: {
        count: 5,
        p50_ms: 200.0,
        p95_ms: 5000.0,
        p99_ms: 5000.0,
      },
      failure_reasons: {
        do_not_honor: 1,
        outage: 1,
        timeout: 1,
      },
    },
    B: {
      volume: 2,
      captured: 2,
      failed: 0,
      declined: 0,
      success_rate: 1.0,
      latency: {
        count: 2,
        p50_ms: 2000.0,
        p95_ms: 6000.0,
        p99_ms: 6000.0,
      },
      call_latency: {
        count: 2,
        p50_ms: 300.0,
        p95_ms: 400.0,
        p99_ms: 400.0,
      },
      failure_reasons: {},
    },
  },
  revenue_recovered_by_rescue_path: {
    retry: {
      count: 1,
      amount_minor_by_currency: {
        USD: 2000,
      },
    },
    failover: {
      count: 1,
      amount_minor_by_currency: {
        EUR: 3000,
      },
    },
    redrive: {
      count: 0,
      amount_minor_by_currency: {},
    },
  },
  time_to_explanation: {
    available: true,
    sources: {
      model: {
        count: 1,
        p50_ms: 2000.0,
        p95_ms: 2000.0,
      },
      rules: {
        count: 1,
        p50_ms: 3000.0,
        p95_ms: 3000.0,
      },
    },
    all: {
      count: 2,
      p50_ms: 2000.0,
      p95_ms: 3000.0,
    },
    fallback_rate: 0.5,
    fallback_reasons: {
      model_timeout: 1,
    },
    fallback_cause_mismatch: 0,
    fallback_model_failures: 1,
    backlog_max: 1,
    backlog_end: 0,
  },
};

export const baselineData: BaselineData = {
  available: true,
  label: "synthetic data, static-routing baseline",
  synthetic: true,
  scenario: "processor-a-outage",
  seed: 7,
  run: 1,
  run_date: null,
  baseline_description:
    "static routing: ROUTING_STRATEGY=static, every payment to Processor A, no failover, no retry (ADR-0009)",
  success_rate_static_pct: 58.0,
  success_rate_relay_pct: 89.0,
  uplift_pp: 31.0,
  revenue_recovered: {
    EUR: 3032328,
    GBP: 1618218,
    JPY: 902033,
    USD: 6810094,
  },
  revenue_by_rescue_path: {
    retry: {
      EUR: 2832363,
      GBP: 1446165,
      JPY: 902033,
      USD: 6713460,
    },
    failover: {
      EUR: 199965,
      GBP: 172053,
      USD: 96634,
    },
    redrive: {},
  },
};

export const unavailableBaseline: BaselineData = { available: false };
