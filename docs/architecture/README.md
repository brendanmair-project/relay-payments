<!-- FOLDER GUIDE from templates/projects/skeleton in the workspace. Refreshed by maintenance/project-docs.ps1; edit the template, not this copy. -->

# Architecture

How the system is built. The design task writes these before any code task that depends on them (plan-review check PR-21).

| File | Holds |
| --- | --- |
| `system-context.md` | The system, its users and every outside system it talks to |
| `containers.md` | Each deployable part (API, worker, web, database, queue, model server) and what flows between them |
| `api-contract.md` | Every endpoint: access rule, request, response, error shape, idempotency, pagination |
| `data-model.md` | Tables, columns, constraints, indexes and retention |
| `constraints.md` | Non-negotiable limits (cost, licences, local-first, privacy) |

Rules: documents must agree with each other and with `../decisions/`; a change that alters the schema, the API shape or reported results needs a decision record first.
