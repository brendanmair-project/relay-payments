# ADR-0018: Phase 5 showcase scope and the bolder-but-trustworthy UI direction

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-11-10  
Supersedes: None (amends the UI direction in `AGENTS.md`, which stays in force until this ADR is Accepted and `AGENTS.md` is updated)  
Superseded by: None

## Context and forces

Phases 1 to 4 are built and measured, and the console is deliberately plain: a first-time viewer (an interviewer or recruiter) has to read tables to learn what Relay does. Phase 5 makes the value visible on the first screen.

- Audience: a viewer must understand, within the first screen, the problem (failed payments cost a merchant money and take hours to explain), the AI's role (a local model explains each failure, checked by rules, ADR-0013) and the money saved.
- Constraints: free and open source only (`docs/architecture/constraints.md`); synthetic data only; no hosted AI (ADR-0010); a dependency outside the fixed stack needs an Accepted ADR (ADR-0011); the model never sees the payment description (ADR-0012).
- Existing UI rule (`AGENTS.md`): dense, restrained and trustworthy; monospace for payment ids, amounts and timestamps; status never shown by colour alone; motion only in response to user actions. The owner wants a bolder look without losing that trust.
- Evidence for the choice: three standalone prototypes on data captured from the running stack on 2026-11-10 (`docs/product/prototypes/`), checked with axe at 1280, 375 and 320 px with 0 violations, no horizontal overflow and a leak scan; references and named patterns in `docs/product/prototypes/references/console-contact-sheet.png` and `console-patterns.md`.

## Decision

Owner decisions recorded on 2026-11-10 (REL-62):

1. **Phase 5 scope.** Phase 5 makes Relay show its value with four features: the AI made visible per failure (REL-63), a money-saved headline (REL-64), a visual redesign of the console (REL-65) and a one-click outage story mode (REL-66), closed by an exit review (REL-67).
2. **The local free model stays.** Explanations keep using `granite3.3:2b` through Ollama (ADR-0010) with the rules fallback and cross-check (ADR-0013). No hosted AI API is added.
3. **UI direction: bolder but trustworthy.** The console becomes a polished modern operations look with a strong headline, charts, motion only in response to user actions, and it stays accessible: status is never shown by colour alone, contrast meets WCAG 2.2 AA, axe reports 0 violations at 1280, 375 and 320 px. This amends the UI direction in `AGENTS.md`; the primary updates that line after the owner accepts this ADR.
4. **Libraries only with approval.** Any new frontend library a chosen direction needs (for example a chart or motion library) must be free and open source, pinned to an exact version, licence-checked at that version and recorded in this ADR with the owner's approval before REL-65 uses it. Plain CSS and SVG are preferred. The three prototypes use none.
5. **Every number on the first screen is measured and labelled.** Figures are either measured on the synthetic environment (labelled "synthetic") or derived against the 2-hour manual baseline (labelled "estimated against the 2-hour manual baseline", ADR-0009). Nothing is invented.

## Chosen direction

Chosen by the owner on 2026-11-10: a mix, in this order from top to bottom.

1. **B's value story** opens the console: the problem in one sentence, the money-saved headline and its labels, and the before and after (58% against 89% from the committed results; rescued money by path).
2. **C's AI section** comes next: the five-step strip (Saw, Asked, Answered, Cross-checked, Shown), the explanation panel for one failure, and the case where the rules check disagrees. It uses a light treatment, so the page keeps one theme.
3. **A's dense console** follows: processor health with the failover state, the payments list, and the incident with its AI summary, laid out for an analyst.
4. The "Run the outage demo" control stays visible in the header.

REL-65 builds this from one live run, so that every figure on a page describes the same run. The prototypes mixed two capture runs.

| Option | File | Summary |
|---|---|---|
| A, operations command centre | `docs/product/prototypes/console-a-command-centre.html` | Dense, light, live status first: processor health and failover ribbon, a money-saved KPI strip, the payments table, the AI panel and incident in a side rail. Closest to today's rules. |
| B, value story | `docs/product/prototypes/console-b-value-story.html` | A full-width money-saved headline and before/after bars first, then a three-step problem, AI and money story, then the console in cards. Strongest first screen for a non-technical viewer. |
| C, AI first | `docs/product/prototypes/console-c-ai-first.html` | The explanation is the centre stage: what the model saw, its answer and cross-check verdict, and a visible example where the check disagrees; money saved as a slim banner. Dark. Strongest for showing the AI's role honestly. |

- Chosen: to be filled by the owner.
- Library approvals (name, exact version, licence checked at that version, reason): none requested.

## Alternatives considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Keep the plain console | Zero work, fully consistent with `AGENTS.md` | First screen does not show the problem, the AI or the money | Rejected by the owner |
| A hosted AI API for better explanations | Stronger text | Paid or non-local, breaks ADR-0010 and the free rule | Rejected |
| A chart or motion library | Faster interactive charts | New dependency, licence and audit work, bundle size | Not needed by the prototypes; only with the approval in decision 4 |
| Bolder look with colour-coded status | Quicker to scan | Fails the accessibility rule | Rejected: status keeps a text label and a glyph |

## Consequences

Positive:

- The first screen can show the problem, the AI and the money without reading tables.
- Prototypes already pass axe and overflow checks at three widths, so the chosen direction starts from an accessible base.

Negative and tradeoffs:

- Money-saved figures not yet computed by the API (REL-64) were derived in the prototypes from captured responses and the committed results file; REL-64 must compute them in the API and the console must show those instead.
- Two measurements differ in scope: the committed REL-30 run (success rate 58.0% static against 89.0% with Relay) and the 2026-11-10 capture (88.7% captured of 300). Both are synthetic and both are labelled; the real headline must name its run.
- One prototype capture (the payments list and processor health) came from a second seeded run than the analytics and incident captured earlier the same day; the real console reads one consistent live state.

Operational impact:

- REL-65 changes `frontend/` only after the owner's choice and any library approval; REL-63 and REL-64 add API fields first.

## Validation and review

- Validate with: the three prototypes report 0 axe violations at 1280, 375 and 320 px, no horizontal overflow, no network requests and no leak-scan hits; REL-65 repeats the same checks on the real console.
- Revisit when: the owner changes the direction, a library is proposed, or the first screen fails to show the problem, the AI and the money without scrolling.
- Owner: Brendan.
