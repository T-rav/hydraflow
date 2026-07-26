---
id: 0240
topic: architecture
source_issue: 10622
source_phase: plan
created_at: 2026-07-26T11:28:44.489389+00:00
status: active
corroborations: 1
---

# Keep arch integrity gate out of check() — synthetic repos are tiny

Run minimum-signal invariants as a separate `--integrity` mode, never inside `check()`.

- `check()` runs against minimal synthetic repos in `tests/architecture/test_runner.py` (1 loop, no ports/labels/events)
- A legitimately tiny repo must not red `check()`
- `make arch-check` calls `--check` then `--integrity` as two sequential lines

**Why:** Folding the gate into `check()` reds the existing synthetic-repo tests because they lack the signals the gate requires.
