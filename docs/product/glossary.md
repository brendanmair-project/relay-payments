# Relay — Glossary

## Status
Working definitions for this project, not universal industry definitions. Updated for the payment-operations positioning ([ADR-0002](../decisions/0002-positioning-and-business-problem.md)).

| Term | Working definition in Relay | Note |
|---|---|---|
| **Payment** | A single card payment request for one merchant, with an identity, an amount in minor units and an ISO 4217 currency, a lifecycle state, and a history of events. | Replaces the earlier generic term "transaction". See `docs/architecture/payment-lifecycle.md`. |
| **Processor** | A payment processor that authorizes and captures payments. Relay simulates two: Processor A and Processor B. | Simulated only; no real processor is integrated. |
| **Attempt** | One try of a payment on one processor, numbered by `attempt_no` (1, or 2 for the single retry on the other processor). | Every transition and event carries it. See ADR-0008. |
| **Final** | A payment whose outcome will not change: captured, declined, failed from authorized, failed on attempt 2, or failed with retries disabled. | Stored as `is_final`; metrics count only final payments. |
| **Retrying** | A `failed` payment that is not final and waits for its retry on the other processor. | A UI label, not a separate state. |
| **Sweeper** | The worker's periodic job that fails timed-out attempts and re-drives stalled payments. | See ADR-0008. |
| **Static-routing baseline** | The comparison mode: all payments on Processor A, no failover, no retry (`ROUTING_STRATEGY=static`). | See ADR-0009. |
| **Event** | An immutable record that something happened to a payment or to routing (state change, routing decision, failover, failure). | Stored in the append-only `payment_events` table. |
| **Transactional outbox** | The pattern where a state change and its event row are written in the same database transaction, and a separate process publishes the rows to the event stream. | See ADR-0003. |
| **Timeline** | The ordered list of a payment's events, shown in the API and UI. | One timeline per payment. |
| **Explanation** | A plain-language account of why a payment ended as it did, built from its timeline by a local model (Ollama) or a deterministic rule-based fallback, generated when the payment reaches a final failure and stored. | Never replaces the timeline; labelled with its source. See ADR-0005 and ADR-0009. |
| **Idempotency key** | A client-supplied `Idempotency-Key` header value that makes `POST /payments` safe to retry. | Retained 24 hours. |
| **Synthetic environment** | The simulated processors plus the load generator, with injectable failures and outages, used for development, tests and demos. | A running simulator, not just test fixtures. The generator uses only the public API. |
| **Routing** | The decision of which processor handles a payment attempt. | Rule-based in Phase 1. |
| **Failover** | Routing new payments (and one retry) to the other processor when a processor's recent error rate crosses a threshold. | Threshold is configurable. |
| **Routing optimization** | Adaptive, possibly AI-assisted routing that improves on the rule-based baseline. | Phase 4. |
| **Incident** | A tracked record of an operational problem, such as a processor outage, with a lifecycle (detect, triage, resolve). | Phase 2. May correlate many payments. |
| **Webhook** | An outbound HTTP notification Relay sends to a subscriber when a payment event occurs. | Phase 3. |
| **System of record** | The component whose stored state is ground truth: PostgreSQL. | Redis Streams carries events but is not a source of truth. |
| **Local-first** | The principle that the full product runs on a developer machine via free and open-source tooling, with cloud as optional. | Hard project constraint. |
| **Owner decision** | A decision by Brendan, the sole decision-maker, recorded as an Accepted ADR. | Replaces the earlier product-manager approval gates. |
| **Foundation phase / Phase 0** | The completed phase of product and architecture documentation. | See `docs/product/roadmap.md`. |

## Maintenance note
Add a term here the first time it is used in a way that could be ambiguous across docs. If a term's meaning changes because of an ADR, update this glossary in the same change.
