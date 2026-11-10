# ADR-0005: AI explanation provider

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29  
Supersedes: None  
Superseded by: None

## Context and forces

The "explain this payment" endpoint turns a payment's event timeline into a plain-language explanation. It needs a model provider that respects the free/open-source rule and keeps tests deterministic (risk R3).

- Constraint: Free and open-source only; no paid dependency without an owner decision.
- Quality attribute: Tests and CI must pass with no model available; explanations must be grounded in the event timeline.
- Evidence: `docs/architecture/constraints.md` (proposed default of a local open-source model) and risk R3.

## Decision

We will use a local open-source model served by Ollama for explanations, with a deterministic rule-based fallback that produces an explanation from the event timeline when no model is available, because this keeps the project free, runnable offline, and testable in CI without a model. Any hosted, paid model API requires a separate owner decision recorded as an Accepted ADR.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (no explanation provider) | No work | No AI-assisted explanation, the core differentiator | Not acceptable for the showcase |
| Hosted paid LLM API | Higher quality, no local hardware | Paid, needs credentials, breaks offline and CI determinism | Violates the free/open-source rule without an owner decision |
| Rule-based only | Deterministic, trivial to test | Less natural language, less impressive | Kept as the fallback rather than the only path |

## Consequences

### Positive

- Runs locally at no cost; CI needs no model.
- The fallback guarantees the endpoint always answers.

### Negative and tradeoffs

- Local model quality and speed depend on the developer machine.
- Two code paths to test and keep consistent.

### Follow-on work

- Accepted in REL-25 (2026-10-30): the model is `granite3.3:2b` under Apache 2.0 ([ADR-0010](0010-local-model.md)), served by Ollama on the host and reached at `OLLAMA_URL`; the `explainer` container writes automatic explanations (ADR-0012). Ollama itself stays outside compose.
- Mark model-generated text as such in the response and never let it replace the raw timeline.

## Validation and review

- Validate with: unit tests on the fallback and a fake model (no model in CI); the manual quality check `python -m app.explain.quality` (REL-25.8) that every citation is valid and the stated cause matches the rules cause.
- Revisit when: explanation quality is inadequate for the demo, or the owner approves a hosted API.
- Reversal/migration cost: Low; the provider sits behind an interface.
