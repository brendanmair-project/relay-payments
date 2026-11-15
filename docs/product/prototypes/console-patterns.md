# Console design patterns (REL-62)

Audience: interviewers and recruiters who must understand, within the first screen, the problem (failed payments cost a merchant money and take hours to explain), the AI's role (a local model explains each failure, checked by rules) and the money saved. Direction (owner, 2026-11-10): bolder but trustworthy.

## References

22 real sites were screenshotted with Playwright at 1280 px on 2026-11-10: Stripe, Stripe Billing, Adyen, Checkout.com, Ramp, Mercury, Plaid, Brex, Datadog, Grafana, Sentry, PagerDuty, incident.io, Rootly, Honeycomb, Linear, Vercel, PostHog, Langfuse, Perplexity, Claude and Cursor. Contact sheet: `references/console-contact-sheet.png`. Some captures include cookie banners (Adyen, Checkout.com, Langfuse, Perplexity, PostHog); they were left in, and the patterns below ignore them. These are marketing pages, not product screens, so they show headline and proof patterns more than dense-table patterns.

## Named patterns

| Pattern | Seen in | Used in |
|---|---|---|
| **Outcome headline with one giant number** (the result first, then the proof) | Ramp ("Time is money. Save both."), Brex, Stripe, Mercury | B: the money-saved figure at 112 px in a serif, A and C: the figure as the first card or band |
| **Before/after bars** (two bars, same scale, the gap is the point) | Ramp, Datadog hero charts | B: success rate 58% against 89%; A: rescued payments by path |
| **Proof strip under the headline** (small chips of supporting facts) | Stripe and Adyen customer rows, Sentry | B: chips under the number; C: the saved banner |
| **AI reasoning panel** (input, answer, cited evidence, verdict) | Perplexity (sources), Langfuse (traces), Honeycomb and Grafana "Ask AI", Cursor | C: three panels (what it saw, its answer, when the check disagrees) and a five-step flow; A and B: one compact panel |
| **Evidence citations** (answer highlights the events it relied on) | Perplexity, Langfuse | all three: timeline rows 3 and 7 marked "cited" |
| **Live status ribbon** (service health first, red and green) | Datadog, PagerDuty, Grafana | A: processor tiles with an error-rate meter and a failover note across the top |
| **Incident card with AI summary** | incident.io, Rootly, PagerDuty | all three: title, state, times, affected count, summary text with its source |
| **Dark operational surface** | Linear, Vercel, Sentry, Mercury | C only, so the contrast between directions is visible |
| **Display serif plus monospace figures** | incident.io, Claude, Linear's code blocks | B: Georgia headline; all: monospace for ids, amounts, times |
| **Step cards "problem, AI, money"** | Ramp, Stripe Billing feature rows | B: three numbered cards |

### Status treatment (all three)

Status is never colour alone. Each status is a bordered word with a glyph (`✓ Captured`, `⊘ Declined`, `✕ Failed`, `↻ Retrying`, `○ Received`, `… Processing`); an avoided processor is a dashed border with `⛔ Avoided`, a preferred one a solid border with `✓ Preferred`; "Received" and "Processing" use a dashed border so they differ from final states without colour.

### Typography and density

- A: system sans at 14 px, monospace figures, tight 4 px rows; highest density.
- B: system sans at 16 px with a Georgia display face for the headline and the big number; low density, large touch targets.
- C: system sans at 15 px, 21 px answer text, monospace evidence; medium density.
- No web fonts and no network requests: all fonts are system stacks.

### Motion

Only button hover and focus transitions, inside `@media (prefers-reduced-motion: no-preference)`. The "Run the outage demo" button is static: clicking it shows a note that the real console would start the story. Nothing animates on load.

## The three directions

| | A, operations command centre | B, value story | C, AI first |
|---|---|---|---|
| File | `console-a-command-centre.html` | `console-b-value-story.html` | `console-c-ai-first.html` |
| First screen | Processor health ribbon, then four KPI cards (money saved first) | Navy hero: the claim, then `$73,321.01` and chips | Saved banner, then the claim and the five-step explanation flow |
| Theme | Light, dense | Warm paper and navy, spacious | Dark graphite |
| Strength | Live status and density; closest to today's rules | Strongest first screen for a non-technical viewer | Shows the AI's work and its failures honestly |
| Risk | The money headline is one card among several | Long page; console is below the fold | Needs the most explanation text per screen |
| Screenshots | `screenshots/console-a-command-centre-1280.png`, `-375.png` | `screenshots/console-b-value-story-1280.png`, `-375.png` | `screenshots/console-c-ai-first-1280.png`, `-375.png` |

All three include: the money-saved headline, the AI panel for one failure (model `granite3.3:2b` running locally, what it saw, its answer, the time taken and the cross-check verdict in words), processor health with failover, the payments list, an incident with its AI summary, and a visible, static "Run the outage demo" control.

## Libraries a real build might want

None is required: all three directions are plain CSS and inline SVG (bars, meters, stacked bars). If the owner wants interactive time-series (for example error rate over the outage window) in REL-65, a chart library would be needed; none is proposed or licence-checked here, and it would go through ADR-0018 decision 4 first. Motion would stay CSS transitions on user actions, so no motion library is needed.

## Data and numbers

Captured on 2026-11-10 from the stack running locally (compose project `relay62proto`, synthetic scenario `processor-a-outage`, seeds 7 and 8). Files in `data/` are the API responses unchanged:

| File | Source |
|---|---|
| `payments-mid-outage.json`, `processor-health-mid-outage.json` | `GET /payments?limit=60` and `GET /processors/health` while Processor A was avoided (second run, seed 8, rate 3 per second) |
| `payment-ai-failure.json`, `explanation-ai-failure.json` | A payment that failed on A (outage), was retried on B and declined (`do_not_honor`), with its stored model explanation |
| `payment-failed-then-captured.json`, `explanation-failed-then-captured.json` | A payment that failed on A and was captured on B; its explanation fell back to the rules text (`cause_mismatch`) |
| `payment-declined.json`, `explanation-declined.json` | A first-attempt decline with a model explanation (not used on a page) |
| `incidents.json`, `incident-detail.json`, `incident-summary.json` | The incident opened for Processor A (first run, seed 7) and its summary |
| `analytics.json`, `analytics-baseline.json`, `processor-health-after.json` | `GET /analytics` after the first run (before the second), `GET /analytics/baseline` and the health after the run |

The API returns no keys; a scan of `data/` and the pages found no key, token, email, phone or local path.

Derived figures, each labelled on the pages:

- Money recovered per currency: the sum of `revenue_recovered_by_rescue_path` over retry, failover and re-drive in `analytics.json` (USD 7,332,101 minor units, shown as $73,321.01; EUR, GBP and JPY alongside). Currencies are never added together. Label: synthetic.
- Success rate 88.7%: captured 266 over final 300 in `analytics.json`. Label: synthetic. The 58.0% against 89.0% bars are from the committed `docs/evaluation/outage-demo/results.json` (run 1, seed 7). Label: synthetic.
- Investigation time saved 68.0 hours: 34 explained failures times (7,200 s minus the measured median time to explanation of 1.06 s). Label: estimated against the 2-hour manual baseline (ADR-0009).
- Time taken for the AI panel: 0.96 s, the stored explanation's `generated_at` minus the `payment.final` event time of that payment.
- Incident recovery 114.4 s: `recovered_at` minus `opened_at`.

Known mismatch: the payments list and processor-health tile come from the second run, the analytics and incident from the first, so counts such as "54 of 94 attempts failed" and "64 payments affected" describe different runs on the same page. The real console reads one live state.

## Check results

Run with axe-core 4.14.0 through `@axe-core/playwright` (tags wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice), Playwright 1.64.1 Chromium, files opened from disk:

| Sample | 1280 | 375 | 320 | Horizontal overflow | Network requests | Leak scan |
|---|---|---|---|---|---|---|
| A | 0 violations | 0 | 0 | none | 0 | clean |
| B | 0 | 0 | 0 | none | 0 | clean |
| C | 0 | 0 | 0 | none | 0 | clean |

The leak scan looked for the API key name and value, email addresses, phone numbers, Windows or Unix home paths, bearer, password, secret and token words, and any URL. Contrast is covered by axe's `color-contrast` rule (WCAG AA). Reduced motion is respected by construction: all transitions are inside `prefers-reduced-motion: no-preference`.
