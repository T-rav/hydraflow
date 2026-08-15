---
id: 2541
topic: patterns
source_issue: 11217
source_phase: plan
created_at: 2026-08-15T06:04:15.266840+00:00
status: superseded
corroborations: 1
superseded_by: 2664
---

# Push-seam gone-branch guard: key on configured-upstream-[gone], not absent origin ref

In `src/pr_manager.py`, detect resurrected branches by reading `git for-each-ref` and flagging an upstream that is configured but `[gone]`.

Avoid keying on "origin ref absent" — a never-pushed branch has no upstream configured, so that signal fires on every first push. The `[gone]` marker means origin deleted it after a prior push, which is the actual orphan condition.

**Why:** The wrong discriminator produces a false WARNING + SYSTEM_ALERT on every first push to any branch.
