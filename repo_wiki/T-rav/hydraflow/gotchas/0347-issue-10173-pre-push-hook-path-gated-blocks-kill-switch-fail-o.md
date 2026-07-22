---
id: 0347
topic: gotchas
source_issue: 10173
source_phase: plan
created_at: 2026-07-22T16:50:02.909718+00:00
status: superseded
corroborations: 1
superseded_by: 0348
---

# Pre-push hook path-gated blocks: kill-switch + fail-open on unresolvable base ref

`.githooks/pre-push` already has precedent for conditional gate blocks: the arch-check block is guarded by `HYDRAFLOW_DISABLE_PRE_PUSH_ARCH_CHECK=1`, runs unconditionally otherwise (no path filter), and fails the push on error. A path-gated variant (e.g. for `make audit`) needs the opposite failure mode for its trigger-decision step: when the diff base (`origin/staging`/`origin/main` merge-base) can't be resolved — detached HEAD, new branch, shallow clone — the trigger script should report "not required" plus a warning and exit non-blocking, not fail the push. CI is the backstop for cases the hook misses.

**Why:** A hook that can hard-fail on ordinary git states (new branches, shallow CI clones) trains developers to bypass pre-push entirely, which is worse than an occasional missed local audit run.
