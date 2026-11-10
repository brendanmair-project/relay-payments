# Relay — Jobs to Be Done

## Status
Decided with ADR-0002. Each job is phrased as: *When [situation], I want to [motivation], so I can [expected outcome].* Each is tagged with its persona (see `personas.md`) and the roadmap phase that delivers it.

## Jobs

1. **Submit and track a payment** — *Sam (Integrating Developer), Dana (Payment Operations Analyst)* — Phase 1
   When a customer pays, I want to submit the payment through a well-defined API and track its lifecycle state, so I can know whether it succeeded, failed or is in progress, and retry safely without creating duplicates.

2. **Reconstruct a payment's history** — *Dana, Marcus (On-call Engineer)* — Phase 1
   When a payment fails or gets stuck, I want one ordered timeline of every event and routing decision that affected it, so I can see what happened without cross-referencing processor dashboards and logs.

3. **Understand why a payment failed** — *Dana, Marcus* — Phase 1
   When I investigate a failed payment, I want a plain-language explanation of the likely cause grounded in the timeline, so I can cut the time from failure to root cause.

4. **Route around a degraded processor** — *Marcus, Dana* — Phase 1 (rule-based), Phase 4 (adaptive)
   When one processor's error rate rises or it goes down, I want payments to move to the other processor automatically, so I lose fewer sales while the problem is fixed.

5. **See processor and platform health at a glance** — *Dana, Marcus* — Phase 2
   When I am responsible for payment uptime, I want dashboards of throughput, latency, error rates and processor health, so I can spot degradation before customers do.

6. **Triage and resolve incidents** — *Marcus* — Phase 2
   When processing degrades, I want a structured incident record linked to the affected payments and events, so I can coordinate the response and track resolution.

7. **Measure what failures cost** — *Dana* — Phase 2
   When I report on payment operations, I want failure and recovery analytics by processor and reason, so I can quantify lost and recovered revenue.

8. **Get notified without polling** — *Sam* — Phase 3
   When a payment changes state, I want a webhook, so I do not have to poll the API.

9. **Integrate quickly** — *Sam* — Phase 3
   When I build on Relay, I want clear docs and a reliable SDK, so I can integrate without reverse-engineering the API.

10. **Optimize routing over time** — *Dana, Marcus* — Phase 4
    When processors' behavior shifts, I want routing that adapts (with AI assistance where useful), so I keep success rates high without manual tuning.

## Notes
- Routing chooses between two simulated processors with different latency, decline-rate and outage profiles; this resolved the former open question about what routing routes between (risk R6).
- Auditability is served by the per-payment event history; there is no separate compliance persona.
