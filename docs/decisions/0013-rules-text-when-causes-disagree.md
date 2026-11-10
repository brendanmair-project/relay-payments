# ADR-0013: Show the rules explanation when the model's cause disagrees

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-10-31  
Supersedes: None (amends how ADR-0005's model text is used)  
Superseded by: None

## Context and forces

The REL-25 quality check (`docs/evaluation/results.md`, 2026-10-30) found that `granite3.3:2b` cites only valid events (10/10) and states amounts correctly, but names a different cause from the rules explainer on 4 of 10 timelines: on retry and failover paths it names the first failure, not the final outcome (risk R18). An analyst reading "authorize outage" for a payment that was captured after failover could act on the wrong cause.

- Constraint: explanations must not invent or mislead (ADR-0005); the raw timeline is always shown beside them.
- Quality attribute: the explanation an analyst sees is the same everywhere: the API, the stored record and the UI.
- Evidence: the quality run lists each mismatch; every model answer names its cause from the rules' fixed list (structured output, REL-25), so the comparison is exact.

## Decision

We will use the rules explanation whenever the model's stated cause differs from the rules explainer's cause for the same timeline, because the rules cause is deterministic and tested, while the model's wording adds value only when it agrees. The check runs where explanations are generated (`api/app/explain/`), not in the browser: the stored row has `source = rules` and `fallback_reason = cause_mismatch`, so the API, the stored record and the payment detail page (REL-27) all show the same text with its source label. The owner chose this on 2026-10-31.

## Alternatives considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Rules text when causes disagree, decided at generation | One answer everywhere; stored and measurable as a fallback reason | More rules text on retry and failover paths | Chosen |
| Show both texts in the UI and let the analyst choose | No information lost | Two conflicting causes on screen for a dense operations tool | Rejected |
| Switch the UI only (keep the model text stored) | No api change | The API and the UI would disagree | Rejected |
| Move to `granite3.3:8b` | Possibly fewer mismatches | 4.9 GB, slower; unmeasured (ADR-0010) | Not now; revisit with the quality check |

## Consequences

Positive:

- An analyst never sees a model-stated cause that contradicts the deterministic rules; risk R18 is mitigated.

Negative and tradeoffs:

- On the current model, retry and failover payments mostly get the rules text, so the fallback rate rises; ADR-0012's reporting splits time to explanation by source, so this stays visible.

Operational impact:

- REL-27 adds the check in `api/app/explain/generate.py` (new fallback reason `cause_mismatch`, a test with a fake model that names a different cause) and shows the source label and fallback reason on the detail page; the quality check reports how often it would apply.

## Validation and review

- Validate with: a unit test where a fake model names a different cause and the rules text is stored with `fallback_reason = cause_mismatch`; the quality check's `cause_match` count after any prompt or model change.
- Revisit when: the quality check shows cause match at 10/10 for a model or prompt change, or analysts need the model wording on retry paths.
- Owner: Brendan.
