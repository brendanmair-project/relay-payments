# Phase 5 exit review (REL-67)

Date: 2026-11-15. Reviewed branch: REL-67 worktree `rel67`, based on `main` at `cd2c802` (REL-62 to REL-66 merged as #433 to #437). All data is synthetic. Live checks used a shell-only `RELAY_API_KEY` (a plain value, no env file), Docker Compose project `rel67`, and the host Ollama with `granite3.3:2b`.

Verdict key: Met, Partly met, Not met. Evidence is a command and what it printed, a file link, or a CI run.

## Summary

All four Phase 5 exit criteria are **Met**. Criterion 4 was **Not met** when this review first ran: two accessibility findings, both fixed in this task with regression tests (section 2).

- The console's first screen leads with the problem, the money saved (revenue recovered per currency, payments rescued, investigation time saved) and the before-and-after success rates, with the AI section starting below (REL-62 to REL-65).
- Every figure on that screen is computed from stored payment events or read from the committed outage-demo results, and labelled "Synthetic data" or "estimated against the 2-hour manual baseline" (REL-64, ADR-0009).
- The outage story runs from one click, with step captions driven by the run's state (REL-66, #437).
- axe reports 0 violations at 1280, 375 and 320 px on the console, analytics and incidents pages, idle and after a finished story run, with no horizontal page scroll.
- Showcase material: six walkthrough screenshots of the new console in the README (230 KB in total), and a rebuilt demo video (a full cut of 5:04 and a 90-second cut of 1:26, with captions and a narration script). Following the owner's decision of 2026-11-14, the video is kept out of the repository and attached to a release of the public copy.

## 1. Roadmap exit criteria (`docs/product/roadmap.md`, Phase 5)

| Criterion | Verdict | Evidence |
|---|---|---|
| A viewer understands the problem, the AI's role and the money saved within the first screen | **Met** | [Screenshot 1](../images/walkthrough/01-console-first-screen.png) at 1280 by 900 px. The problem statement, the "Money saved" headline and "Before and after" are above the fold, and "How the AI explains failures" starts on the same screen. The e2e test `console.spec.ts` checks this heading order: Money saved, then the AI section, then Processor health, then Latest payments |
| Every number on that screen is measured on the synthetic environment and labelled; none is invented | **Met** | See section 1.1 |
| The outage story runs from one click | **Met** | REL-66 (#437): `/control/story/run` and the "Run the outage demo" control; e2e `story.spec.ts` in CI. This review: `POST /api/demo/run` answered 202; the run reached `outage` at payment 48 and ended `finished` |
| The console passes axe with 0 violations at 1280, 375 and 320 px with no horizontal overflow | **Met** (after the fixes in section 2) | Section 2 |

### 1.1 Where the first-screen numbers come from

| Figure | Source | Label on screen |
|---|---|---|
| Revenue recovered per currency, payments rescued (by failover and by retry) | `money_saved()` in `api/app/reporting/metrics.py` over stored payment events for the last 24 hours (REL-64); the definitions are under "How these are counted" | "Synthetic data" |
| Investigation time saved | The 2-hour manual baseline (an ADR-0009 assumption) minus the measured time from final failure to stored explanation, per explained failure | "estimated against the 2-hour manual baseline" |
| Before and after (58.0% with static routing, 89.0% with Relay, +31.0 pp) | [`outage-demo/results.json`](outage-demo/results.json), run 1, seed 7 (REL-30) | "Synthetic data", with the seed and run named |

Finding (owner decision 2026-11-15, follow-up): during a story run the headline shows "0 by failover". This is correct by the REL-64 definition, which counts only payments that failed an attempt and were captured on a later one. Payments sent straight to Processor B while A was avoided never failed, so they are not counted anywhere. A "protected by failover" figure is planned as a follow-up with its own decision record; until then, the video script explains the 0.

## 2. Accessibility check

Command: a Playwright and axe-core script outside the repository. It runs every axe rule at all impact levels at 1280, 375 and 320 px on `/`, `/analytics` and `/incidents`, and measures `scrollWidth - clientWidth`.

First run, on a stack the video worker had used (story run finished): **failed**.

| Finding | Where | Cause | Fix (this task) | Regression test |
|---|---|---|---|---|
| `color-contrast` (serious), 1.41:1 against 4.5:1 required | `/` at every width, after a story run: "See Revenue recovered in the Money saved headline below..." | `StoryMode` used `.fine`, whose `--hero-muted` colour is meant for the dark hero, on the white page. `OutageControl`'s read-only note during a run had the same problem | Both components now use `.fine-dark` (`--muted`, already checked at 4.5:1 or above) | `tests/unit/css-accessibility.test.ts`: `.fine` may appear only in `ValueStory.tsx` (red before the fix: `OutageControl.tsx` and `StoryMode.tsx` also used it) |
| Horizontal overflow of 13 px | `/analytics` at 320 px | The "Against the static-routing baseline" figures list used a `max-content` grid column that could not shrink | `.figures` columns are `minmax(0, max-content) minmax(0, 1fr)`, and terms and values wrap with `overflow-wrap: anywhere` | `tests/e2e/analytics.spec.ts`: no horizontal page scroll at 320 px (red before the fix: received 13) |

Why the existing tests missed both: the console's axe test runs only on the idle page and counts only serious or critical violations, so the hint text shown after a run was never on screen. The overflow test covered only the console, at 390 px.

After the fixes (frontend image rebuilt): `AXE_WIDTHS=PASS`, with 0 violations and 0 overflow for all 9 page and width pairs, both idle and after a finished story run. Mid-run, `/` also showed 0 violations at 1280 and 375 px.

## 3. Other evidence

- `scripts/smoke_stack.py` against the `rel67` stack: `SMOKE_STACK=PASS`.
- `worktree-check.ps1 -Target web`: `CHECK=PASS` (lint, format, typecheck, build, 255 Vitest tests).
- `tests/e2e/analytics.spec.ts` against the live stack: 5 passed.
- CI on `main` before this task: `success` (head `cfba5ea`).
- Walkthrough screenshots: retaken from a clean stack during a story run, with real model explanations. Six PNG files totalling 230,428 bytes replace six totalling about 458 KB. No key, path, email or token is visible.
- Demo video: built with the `demo-video` skill and kept outside the repository.
  - Frame check: one frame every 2 seconds across both cuts, then again on the re-recorded scene.
  - Text check: the script and captions were searched for keys, tokens, paths and emails, with no hits.
  - Every number on screen comes from the running product or a committed results file.
  - The first AI scene showed a real model answer with an unsupported claim ("the funds had been collected before the capture"). It was re-recorded with a clean expired-card example on the owner's decision of 2026-11-15. The rules cross-check compares the cause, not every sentence (ADR-0013), so this kind of claim can pass it.

## 4. Follow-ups

1. A "protected by failover" figure on the Money saved headline, with a decision record (section 1.1): owner decision 2026-11-15, after REL-67.
2. Hosted replay for hiring managers, showing the console, an operational dashboard and a live step view of the AI operations agent (Relay Phase 6): owner decisions 2026-11-14. Plan Phase 6 first, with plan-review.
3. The model can write a sentence the rules cross-check does not catch (section 3). Consider a sentence-level check in Phase 6, where the agent's steps are shown live.

## Owner review

Owner review (2026-11-15): approved. Phase 5 closes with all four exit criteria met. The public copy refresh and the video release follow after the owner's separate go-ahead.
