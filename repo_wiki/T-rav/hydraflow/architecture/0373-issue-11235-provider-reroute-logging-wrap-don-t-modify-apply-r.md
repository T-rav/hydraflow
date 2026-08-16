---
id: 0373
topic: architecture
source_issue: 11235
source_phase: plan
created_at: 2026-08-16T05:30:59.489410+00:00
status: active
corroborations: 1
---

# Provider reroute logging: wrap, don't modify, apply_repo_provider

Add a public wrapper (`apply_repo_provider_logged` in `src/repo_backend.py`) that delegates to `apply_repo_provider` and emits one INFO with a literal format string naming source + resolved provider/model — only when the provider changed. Unchanged provider logs nothing. Mirror the pattern at `src/base_runner.py:258-264`. The wrapper must be public (no `_` prefix) for cross-module import.

**Why:** Keeps observability without coupling the core resolver to logging or breaking callers that don't need the log.
