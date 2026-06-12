---
id: 0007
topic: testing
source_issue: 9080
source_phase: review
created_at: 2026-06-12T09:06:10.457668+00:00
status: active
corroborations: 1
---

# Verify implementation files exist before raising a PR for review

Confirm that every file named in the spec actually exists in the branch before posting the PR — auto-generated commits (arch diagrams, wiki updates) create a plausible-looking branch with zero implementation.

- Check `git diff --name-only origin/staging...HEAD` against the spec's file list.
- Five auto-generated commits with none containing `src/contract_github_sandbox.py` is a common false-ready signal.

**Why:** Reviewers waste a full review cycle on a skeleton PR; the gap only surfaces when reviewers look for the core files.
