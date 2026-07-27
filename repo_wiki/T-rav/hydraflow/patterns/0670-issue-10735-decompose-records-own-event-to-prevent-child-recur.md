---
id: 0670
topic: patterns
source_issue: 10735
source_phase: plan
created_at: 2026-07-27T20:01:28.594800+00:00
status: active
corroborations: 1
---

# Decompose records own event to prevent child recursion

When the self-solve ladder invokes decompose, decompose records its own event on `ConvergenceLedger`. Children spawned by decompose start with a fresh `GiveUpWindow`.

- `src/self_solve_terminal.py` + `src/give_up_window.py`
- Children cannot inherit the parent's exhausted window

**Why:** Without the self-recorded event, a thrashing child could recurse through decompose indefinitely, defeating the window's purpose.
