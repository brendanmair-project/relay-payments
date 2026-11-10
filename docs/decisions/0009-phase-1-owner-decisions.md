# ADR-0009: Phase 1 currencies, UI access, stored explanations and demo measurement

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-30  
Supersedes: None  
Superseded by: None

## Context and forces

The 2026-09-30 plan review found six open choices that change the schema, API shape or reported results. They were put to the owner, who chose the recommended option for each.

- Constraint: Free and open source only; any new library needs an Accepted ADR (`docs/architecture/constraints.md`).
- Quality attribute: Results a reviewer can reproduce and trust; the API key never reaches a browser.
- Evidence: Relay plan review of 2026-09-30 (gaps C1 to C6), recorded in `docs/delivery/process-log.md` (session 5).

## Decision

We will apply the following, because each makes Phase 1 measurable and safe without new dependencies:

1. **Currencies.** Relay accepts USD, EUR, GBP (2 minor-unit digits) and JPY (0 digits) from one table in code; any other code is rejected with 422. No currency library.
2. **API access.** Every API endpoint, reads included, requires the `X-API-Key` header. The UI calls the API only through Next.js server routes that add the key; the browser never receives it, and no CORS is needed.
3. **Stored explanations.** When a payment reaches a final failure, an explanation is generated outside the payment path and stored with its source (model or rules), model name and time. `GET /payments/{id}/explanation` returns the stored one and can regenerate on request. Time to explanation is measured from the final failure event to the stored explanation.
4. **Manual baseline.** Rebuilding one failed payment's story by hand is assumed to take 2 hours. Results state this as an assumption, not a measurement.
5. **Static-routing baseline.** The baseline routes everything to Processor A with no failover and no retry (`ROUTING_STRATEGY=static`). "Revenue recovered" is the captured amount under Relay routing minus the captured amount under the baseline, per currency, on the same seeded scenario.
6. **Reproducibility.** Simulator outcomes derive from the seed, payment id and attempt number, independent of arrival order. A result is reproducible when three runs with one seed agree within 1 percentage point on success rate and 1% on revenue recovered; the tolerance is printed with the results.

Amended 2026-10-09 by [ADR-0012](0012-phase-1-review-decisions.md): draws are seeded on a deterministic payment `reference` instead of the random payment id, so runs repeat per payment and the baseline is compared payment by payment (item 6); time to explanation is reported per source with the fallback rate, and revenue recovered is split by retry and failover (items 3 and 5).

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (undecided) | No commitment | REL-14, REL-17, REL-25 and REL-30 cannot be specified | Blocks Phase 1 |
| Full ISO 4217 list via a library | Any currency | New dependency and ADR | Four currencies exercise both minor-unit cases |
| Unauthenticated read endpoints | Simpler UI calls | Payment data open to anything on the network | Server routes cost little and keep one rule |
| Explanations generated on each request | No storage | Time to explanation cannot be measured; a model call on every page view | Stored explanations are faster and measurable |
| Baseline that keeps the retry | Isolates failover alone | Smaller, harder-to-read numbers | Owner chose the plain static baseline |
| Exact reproducibility with a simulated clock | Identical numbers | Simulated time across async services is a large build | Seeded outcomes plus a stated tolerance are honest and cheap |

## Consequences

### Positive

- REL-14, REL-17, REL-18, REL-22, REL-25, REL-26 and REL-30 have concrete acceptance criteria.
- The north-star and outcome metrics become computable.

### Negative and tradeoffs

- The 2-hour baseline is an assumption; the README must say so (risk R10).
- Results are reproducible within a tolerance, not to the digit.

### Follow-on work

- Update `docs/product/metrics.md`, `docs/architecture/payment-lifecycle.md` and `docs/architecture/system-context.md` (done with this ADR).
- Apply in tasks REL-14, REL-17, REL-18, REL-22, REL-25 to REL-28 and REL-30.

## Validation and review

- Validate with: REL-30's three seeded runs within tolerance; a Playwright check that no API key appears in browser traffic; 422 for a currency outside the table.
- Revisit when: more currencies, a second merchant or public demo hosting are wanted.
- Reversal/migration cost: Low; each item is local to one module.
