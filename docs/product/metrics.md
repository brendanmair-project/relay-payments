# Relay — Metrics

## Status
Decided with ADR-0002; measurement rules decided with ADR-0009 and refined by ADR-0012 (paired runs, reporting per source). No baseline data exists yet (pre-implementation). All measurements are taken on the synthetic environment.

## North star
**Median time from a payment failure to an explained root cause.** It captures the core problem: payment-operations staff spend hours rebuilding what happened. Target direction: minutes, not hours. Measured from a payment's final failure event to the moment its stored explanation exists (explanations are generated when a payment reaches a final failure, ADR-0009). The comparison baseline is an assumed **2 hours** to rebuild one failed payment's story by hand; results must state that this baseline is an assumption, not a measurement.

Reported per source (ADR-0012): the median and P95 for model explanations and for rule-based ones separately, with the fallback rate (share of final failures explained by the rules) and the largest explanation backlog during the run, measured after warming the model. The rules answer in milliseconds, so a combined median would improve when the model fails; the per-source figures prevent that. The model quality check also compares each model explanation's stated cause with the rules explainer's cause for the same timeline.

## Business outcome metrics
Measured on the synthetic environment against a static-routing baseline: all traffic on Processor A, no failover and no retry (`ROUTING_STRATEGY=static`), using the same seeded load and the same injected outages:

- **Simulated revenue recovered by Relay routing:** total `amount_minor` of payments captured under Relay routing minus the total captured under the baseline, per currency; also split by how each recovered payment was rescued: the single retry on the other processor (`payment.routed` reason `retry`) or failover routing (reason `failover`), because the static baseline has neither (ADR-0012).
- **Payment success-rate uplift:** final captured payments divided by created payments, compared with the baseline. When every payment is final, captured over final equals captured over created, so the REL-30 results are unchanged by the single definition below.

Only final payments count (a `failed` payment that is still retrying is not final; see `docs/architecture/payment-lifecycle.md`).

**Reproducibility:** simulator outcomes derive from the seed, the payment's `reference` and the attempt (ADR-0012). The load generator gives every scenario payment a deterministic reference, so runs with one seed draw the same outcome for the same payment, and the baseline and Relay runs are compared payment by payment. A result is reproducible when three runs with one seed agree within 1 percentage point on success rate and 1% on revenue recovered; the tolerance is printed with every result. Without references (random payment ids) revenue recovered would vary by about 2.4% between runs of 10,000 payments, which is why references are required for the demo.

## Reliability guardrails
- Payment success rate for the synthetic load, split by processor. **One definition (REL-57):** captured payments divided by final payments, where final means captured, declined or failed, so declines count in the denominator; a payment still retrying is not final and is not counted. Per processor, each final payment counts once under the processor that handled it (the processor of its final attempt). The Grafana panel (Success rate by processor), `GET /analytics` and the guardrail report all use it, and `docs/architecture/api-contract.md` states it for API users.
- P50/P95/P99 payment processing latency (creation to final state).
- API 5xx rate.
- Event publishing lag (time from the event being written to it appearing in Redis Streams).
- Payments not final after the sweeper threshold (target: zero).

## Engineering-health guardrails
- CI pass rate (pytest, frontend tests and Playwright in GitHub Actions).
- Test coverage of the state machine and idempotency rules.
- `docker compose up` from a clean checkout must always bring up a fully working environment; this is a hard guardrail, checked at each phase exit.
- Zero paid dependencies introduced without an owner decision recorded as an Accepted ADR.

## Later
- Mean time to detect and resolve injected incidents (Phase 2).
- Webhook delivery success rate and time to a first successful API call from the docs (Phase 3).
