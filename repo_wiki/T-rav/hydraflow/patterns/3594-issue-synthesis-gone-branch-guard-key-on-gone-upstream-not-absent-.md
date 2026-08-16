---
id: 3594
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.199238+00:00
status: superseded
corroborations: 1
supersedes: 3447
superseded_by: 3739
---

# Gone-branch guard: key on [gone] upstream, not absent origin ref

In `src/pr_manager.py`, detect resurrected branches by reading `git for-each-ref` and flagging an upstream that is configured but `[gone]`. Avoid keying on "origin ref absent" — a never-pushed branch has no upstream configured, so that signal fires on every first push.

Example: The `[gone]` marker means origin deleted it after a prior push, which is the actual orphan condition.

**Why:** The wrong discriminator produces a false WARNING + SYSTEM_ALERT on every first push to any branch.
