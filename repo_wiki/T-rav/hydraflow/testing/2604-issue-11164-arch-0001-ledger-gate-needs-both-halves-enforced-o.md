---
id: 2604
topic: testing
source_issue: 11164
source_phase: plan
created_at: 2026-08-14T18:58:35.986570+00:00
status: stale
corroborations: 1
stale_reason: source issue #11164 closed
---

# ARCH-0001 ledger gate needs both halves enforced on ledger-only PRs

ARCH-0001's console-charter conformance has two halves: `make console-conformance` (shape/numbering/personas/chairs/staleness/git-immutability) and `tests/test_console_conformance.py`. Both live in the `audit` job gated on `core_python || ci`. A PR touching only `agents/console/decisions/arch/0001-console-charter.md` evaluates both filters false, so neither half runs. Fix by OR-ing a `console_ledger: ['agents/**']` output into the `audit` job's `if:`.

**Why:** A gate that never runs for the one change class it exists to catch is worse than no gate — it creates false assurance.
