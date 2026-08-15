---
id: 2605
topic: testing
source_issue: 11164
source_phase: plan
created_at: 2026-08-14T18:58:35.986576+00:00
status: stale
corroborations: 1
stale_reason: source issue #11164 closed
---

# Minimal CI gate-widening beats new jobs when an existing job already has the right checkout

To make a gate reachable for a new path class, prefer widening an existing job's `if:` over adding a new job or expanding a heavy filter. `audit` already takes `fetch-depth: 0` and runs `make console-conformance` on full history — OR-ing in `console_ledger` closes both ARCH-0001 halves without dragging `core_python`'s lint/typecheck/security/pytest lane onto markdown-only PRs.

Alternatives considered: new dedicated `console-conformance` job (more surface, duplicate `ci-gate.needs` entry) or adding `agents/**` to `core_python` (heavy lane on ledger PRs).

**Why:** Widening the wrong filter pulls unrelated heavy work onto trivial PRs and slows feedback.
