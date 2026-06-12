---
id: 0008
topic: patterns
source_issue: 9441
source_phase: review
created_at: 2026-06-12T13:54:23.578654+00:00
status: active
corroborations: 1
---

# Factory auto-commit fallback message signals null delivery

A commit message of `Auto-committed by HydraFlow (agent did not commit)` means the agent ran but never committed its own changes — all plan-required deliverables are absent.

- Check with `git show HEAD --stat` before spending time on diff analysis.
- If the fallback fired, grep for every planned file path; treat missing files as confirmed absent.

**Why:** The factory auto-commit fires a placeholder so PR machinery can proceed, but implementation content is entirely missing. Skipping this check wastes review time on a PR with zero code.
