---
id: 1158
topic: gotchas
source_issue: 10726
source_phase: plan
created_at: 2026-07-27T18:34:31.163810+00:00
status: active
corroborations: 1
---

# Finding body command must satisfy _surfacing_answered closure gate

The resolution command a HITL finding body prints must change the exact state that `_surfacing_answered` (`src/escape_ledger_loop.py:189`) checks. If the body prints a command that doesn't touch the gated field, the next `_reconcile_surfaced_issues` pass leaves the issue open. **Why:** A disconnect between "what the body says to do" and "what the code checks to close" strands surfaced issues open indefinitely — the exact failure #10577 exists to prevent.
