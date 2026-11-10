# Relay — Personas

## Status
Decided with ADR-0002. Personas are archetypes for a portfolio project on synthetic data; they are not research findings.

## Primary persona — Payment Operations Analyst ("Dana")
- Works on the merchant's payment-operations team and handles failed and stuck payments day to day.
- Pain: rebuilding what happened to a payment across two processor dashboards and logs takes hours per incident.
- Needs: one timeline per payment, a plain-language explanation of why it failed, and a quick view of which processor is misbehaving.
- Primary surfaces: payment list, payment detail (timeline and explanation); later incidents, dashboards and analytics.

## Secondary persona — On-call Engineer ("Marcus")
- Gets paged when payment processing degrades.
- Needs: fast triage, evidence of which processor failed and when, confirmation that failover engaged, and (later) a structured incident record.
- Primary surfaces: event history, routing decisions, explanation; later incident management and monitoring.

## Later persona — Integrating Developer ("Sam")
- Builds against the Relay API from the merchant's checkout or back office.
- Needs: accurate API docs, idempotent payment creation, reliable webhooks and an SDK.
- Primary surfaces: REST API now; webhooks, developer docs and SDK in Phase 3.

## Dropped or out of scope
- **Platform Engineer:** dropped; that is the builder of Relay, not a user.
- **Risk/Compliance:** out of scope for a synthetic-data project. The per-payment event history gives an audit trail, which is the extent of it.
- **End customers (payers):** not modeled; they are simulated by the load generator.
