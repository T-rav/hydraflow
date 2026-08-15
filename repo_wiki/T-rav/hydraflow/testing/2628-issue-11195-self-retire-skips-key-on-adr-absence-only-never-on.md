---
id: 2628
topic: testing
source_issue: 11195
source_phase: plan
created_at: 2026-08-15T01:07:17.473992+00:00
status: active
corroborations: 1
---

# Self-retire skips key on ADR absence only, never on status

When making an ADR pin self-retire, the skip condition must be absence of the ADR only — never soften `status == "Superseded"` into a skip.

- Correct: skip when the ADR file is gone or renumbered.
- Wrong: skip when `status != "Superseded"`, which leaves a vacuous pin if the ADR is later revived.
- `test_intact_fixture_tree_is_clean` and the counter-pin in `test_issue_11195.py` catch unconditional or always-true skips.

**Why:** An unconditional skip kills the pin silently; keying on status creates a hole where the pin stops testing what it was built to test.
