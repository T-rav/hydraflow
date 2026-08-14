---
id: 1278
topic: gotchas
source_issue: 11110
source_phase: plan
created_at: 2026-08-14T08:05:02.917546+00:00
status: active
corroborations: 1
---

# Git pathspec trailing slash silently matches no blob

When combining a git pathspec with `--diff-filter`, a trailing slash like `{decisions}/*/` matches directories only, not blobs — so `--diff-filter=M` always returns empty and the check silently no-ops. Use `{decisions}/*` or `{decisions}/**` for recursive blob matching.

In `scripts/check_console_conformance.py:125`, the trailing slash made the entire `check_git=True` branch dead code.

**Why:** A pathspec matching no blob produces no error — the check passes vacuously, and the immutability guarantee is silently unenforced.
