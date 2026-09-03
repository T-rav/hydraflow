---
id: 2809
topic: testing
source_issue: 12055
source_phase: plan
created_at: 2026-09-02T21:55:38.779767+00:00
status: active
corroborations: 1
---

# Use `_tracked_paths(repo)` to scan all committed files instead of hardcoded allowlists

Replace hardcoded root lists (`scanned_roots = ["src", "scripts", ...]`) with iteration over `_tracked_paths(repo)` minus fixtures and self-exemption.

Example: test_beads_manager.py currently filters by hardcoded directories; widened scan catches violations in `docs/`, prompts, and assets (e.g., `bd` commands in src/agent/_prompts.py instructions).

**Why:** Hardcoded allowlists drift from actual committed state and miss agent-facing documentation that ships with the repo.
