---
source: feedback_skip_hooks_on_push.md
name: Skip lint on push when told PR is good
description: When user says the PR is good / code quality is fine, don't re-run lint/typecheck
  on push — just push with --no-verify
status: wontfix
issue: null
promoted_in: null
wontfix_reason: No code surface reachable from this repo. --no-verify is a client-side
  flag the server cannot see, and a hook cannot police the flag that disables hooks.
created: '2026-04-07'
---

When the user says a PR is good or explicitly says not to lint/typecheck, just push directly with `--no-verify`. Don't force quality gates the user has already cleared or dismissed.

**Why:** User found the pre-push hook (make quality-lite) unnecessarily slow when they've already validated the code.

**How to apply:** If the user indicates code quality is fine or tells you to skip checks, use `git push --no-verify` instead of waiting for hooks.
