# ADR-0010: Local model for explanations: IBM Granite 3.3 2B

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-10-01  
Supersedes: None (settles the model choice left open in ADR-0005)  
Superseded by: None

## Context and forces

ADR-0005 chose a local model served by Ollama with a rule-based fallback but left the model open. The model installed for REL-10, `llama3.2:3b`, is governed by the Llama 3.2 Community License and acceptable-use policy, which is not an OSI-approved open-source licence (risk R13). The 2026-09-30 plan reviews of all five portfolio projects raised the same conflict, and on 2026-10-01 the owner accepted the recommendation to use an OSI-licensed model everywhere.

- Constraint: free and open-source software only (`docs/architecture/constraints.md`); the model ships with the demo setup, so its licence counts.
- Quality attribute: small enough to run on the owner's laptop and in an optional container; tests never need it (the fallback covers CI).
- Evidence: https://ollama.com/library/granite3.3 lists `granite3.3:2b` under Apache 2.0 at 1.5 GB (checked 2026-10-01); the Llama 3.2 licence page on ollama.com is the community licence and acceptable-use policy. `granite3.3:2b` was pulled on 2026-10-01 and answered a prompt through the local API.

## Decision

We will use `granite3.3:2b` (IBM Granite 3.3, 2 billion parameters, Apache 2.0) served by Ollama on the host, reached from containers at `OLLAMA_URL` (default `http://host.docker.internal:11434`), because it meets the open-source rule, is the smallest verified option, and is already installed and working. `llama3.2:3b` stays installed but is not used by any project. The rule-based fallback from ADR-0005 is unchanged.

## Alternatives considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Keep `llama3.2:3b` and accept its licence in an ADR | Already installed; good quality for its size | Breaks the open-source rule; a portfolio reviewer may flag it | Rejected |
| `granite3.3:8b` | Better answers | 4.9 GB; slower on a laptop | Rejected for Phase 1; revisit if explanation quality fails its check |
| Phi-3.5 mini (3.8B) | Strong small model | Licence not shown on the Ollama page when checked; larger | Rejected (unverified licence) |

## Consequences

Positive:

- Every project uses one model with a verified open-source licence; risk R13 is resolved.

Negative and tradeoffs:

- A 2B model may write weaker explanations; the explanation-quality check in REL-25 decides whether to move to the 8B size.

Operational impact:

- REL-25 uses `granite3.3:2b` and moves ADR-0005 to Accepted citing this record; the optional `--profile llm` container pulls the same tag.

## Validation and review

- Validate with: REL-25's check that an Ollama-backed explanation cites events from the timeline, with `api-tests` passing when no model runs.
- Revisit when: explanation quality fails its check, or a newer Apache or MIT model of similar size is verified.
- Owner: Brendan.
