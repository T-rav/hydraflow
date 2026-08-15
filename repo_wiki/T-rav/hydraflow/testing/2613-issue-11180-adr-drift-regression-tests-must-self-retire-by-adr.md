---
id: 2613
topic: testing
source_issue: 11180
source_phase: plan
created_at: 2026-08-14T23:23:17.598854+00:00
status: active
corroborations: 1
---

# ADR-drift regression tests must self-retire by ADR number

Resolve ADRs by number through `ADRIndex(_ADR_DIR).adrs()` and `pytest.skip` when the ADR is absent or not in `LIVE_ADR_STATUSES`. Never hard-code the markdown filename.

- ❌ `(_ADR_DIR / "0049-trust-loop-kill-switch-convention.md").read_text(...)` — breaks on renumber/retire.
- ✅ `adr = next((a for a in index.adrs() if a.number == 49), None)` then skip if `None` or not `is_live`.

**Why:** Routine ADR renumbering or retirement must not turn an unrelated PR red in CI — the convention is documented in `tests/regressions/test_issue_10440.py` and enforced by `tests/regressions/test_issue_11180.py`.
