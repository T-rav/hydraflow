---
id: 1037
topic: gotchas
source_issue: 10567
source_phase: review
created_at: 2026-07-26T01:57:49.298967+00:00
status: stale
corroborations: 1
stale_reason: source issue #10567 closed
---

# PR label getters must mirror sibling across Port/Manager/Fake layers

When adding a new `PRPort` query method (e.g. `get_pr_labels`), mirror an existing sibling method's contract across all three layers, not just its parsing logic.

- `src/ports.py` docstring must restate fail-closed/propagate-on-error semantics, matching `get_issue_labels`'s documented contract.
- `PRManager` implementation and `FakeGitHub` test double should match the sibling's shape (cassette schema, dispatcher wiring).
- `get_pr_labels` initially omitted the error-propagation clause in its docstring; fixed in commit `a0a105d2`.

**Why:** copying logic but skipping the contract docs silently erodes the error-handling guarantees callers depend on.
