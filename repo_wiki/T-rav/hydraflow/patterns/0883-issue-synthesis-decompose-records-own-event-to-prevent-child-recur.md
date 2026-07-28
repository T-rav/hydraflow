---
id: 0883
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:29:08.551994+00:00
status: active
corroborations: 1
supersedes: 0828
---

# Decompose records own event to prevent child recursion

When the self-solve ladder invokes decompose, decompose must record its own event on `ConvergenceLedger` (`src/self_solve_terminal.py` + `src/give_up_window.py`) so children spawned by decompose start with a fresh `GiveUpWindow`.

Example: Children cannot inherit the parent's exhausted window — the self-recorded event resets the child's GiveUpWindow.

**Why:** Without the self-recorded event, a thrashing child could recurse through decompose indefinitely, defeating the window's purpose.
