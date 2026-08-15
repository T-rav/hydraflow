---
id: 2611
topic: testing
source_issue: 11178
source_phase: plan
created_at: 2026-08-14T23:03:00.703662+00:00
status: stale
corroborations: 1
stale_reason: source issue #11178 closed
---

# Run full make quality for escape_ledger_loop.py changes

Never run a file-targeted test subset when modifying `src/escape_ledger_loop.py`. It backs 5+ regression pins and cross-cuts multiple loops.

- Run `make quality` in full, not `pytest tests/test_escape_ledger_loop.py`.
- A file subset misses breakage in shared loop module consumers.

**Why:** The shared loop module is imported transitively; a green subset does not mean green quality gate.
