# Architecture Decision Records

This directory holds the Architecture Decision Records (ADRs) for Relay. The owner (Brendan) is the sole decision-maker: a decision is made when the owner records it as an ADR with status `Accepted`. A proposed default written in another document is not authoritative until an Accepted ADR exists.

## Process

1. Copy the structure of an existing ADR (for example `0001-stack.md`) to `NNNN-short-title.md`, using the next number. The structure comes from the workspace template `templates/decisions/ADR.template.md`; keep every heading and the `Template: claude/decision@1` line.
2. Set the status to `Proposed`, fill in every section, and leave no placeholders.
3. When the owner decides, change the status to `Accepted` (or `Rejected`) and update the date.
4. Add or update the row in the log below.
5. Update any doc the decision changes in the same change.

Write an ADR when a decision is expensive to reverse, resolves an open question, or picks one of several viable options. Do not write one for routine, easily reversed details.

## Log

| # | Title | Status |
|---|---|---|
| 0001 | [Fixed technology stack](0001-stack.md) | Accepted |
| 0002 | [Positioning and business problem](0002-positioning-and-business-problem.md) | Accepted |
| 0003 | [Payment event history via transactional outbox](0003-payment-event-history.md) | Accepted |
| 0004 | [Payment fundamentals](0004-payment-fundamentals.md) | Accepted |
| 0005 | [AI explanation provider](0005-ai-explanation-provider.md) | Accepted |
| 0006 | [Observability stack](0006-observability-stack.md) | Accepted |
| 0007 | [Development tooling and CI scope](0007-development-tooling-and-ci-scope.md) | Accepted |
| 0008 | [Payment attempts and processing reliability](0008-payment-attempts-and-processing-reliability.md) | Accepted |
| 0009 | [Phase 1 currencies, UI access, stored explanations and demo measurement](0009-phase-1-owner-decisions.md) | Accepted |
| 0010 | [Local model for explanations: IBM Granite 3.3 2B](0010-local-model.md) | Accepted |
| 0011 | [Phase 1 build decisions: setup, versions, runtime libraries and small rules](0011-phase-1-build-decisions.md) | Accepted |
| 0012 | [Phase 1 review decisions: reproducible paired runs, open-source event store, isolated explanations, UI route access and reporting](0012-phase-1-review-decisions.md) | Accepted |
| 0013 | [Show the rules explanation when the model's cause disagrees](0013-rules-text-when-causes-disagree.md) | Accepted |
| 0014 | [Phase 2 incident detection in its own consumer, and observability as an optional profile](0014-phase-2-incident-detection-and-observability-profile.md) | Accepted |
| 0015 | [Webhook delivery in its own consumer, signed, with a target allowlist](0015-webhook-delivery-signing-and-target-allowlist.md) | Accepted |
| 0016 | [Adaptive routing objective, experiment harness and algorithm](0016-adaptive-routing-objective-harness-and-algorithm.md) | Accepted |
| 0017 | [Second adaptive iteration: a gated hybrid of rules and Thompson sampling](0017-gated-hybrid-routing-second-iteration.md) | Accepted |
