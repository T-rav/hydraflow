---
id: 2787
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:02.164225+00:00
status: active
corroborations: 1
supersedes: 2664
---

# Gone-branch guard: key on [gone] upstream, not absent origin ref

In `src/pr_manager.py`, detect resurrected branches by reading `git for-each-ref` and flagging an upstream that is configured but `[gone]`. Avoid keying on "origin ref absent" — a never-pushed branch has no upstream configured, so that signal fires on every first push.

Example: The `[gone]` marker means origin deleted it after a prior push, which is the actual orphan condition.

**Why:** The wrong discriminator produces a false WARNING + SYSTEM_ALERT on every first push to any branch.
