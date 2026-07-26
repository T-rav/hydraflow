---
id: 0220
topic: architecture
source_issue: 10586
source_phase: plan
created_at: 2026-07-26T02:51:38.701775+00:00
status: active
corroborations: 1
---

# Cross-module tracked repo_wiki reads need a new public RepoWikiStore accessor

`src/repo_wiki.py`'s tracked-entry reader (`_load_tracked_active_entries`, `_split_tracked_entry`) is private. A consumer like `WikiRotDetectorLoop` scanning `repo_wiki/<owner>/<repo>/<topic>/` for active-status entries must get a new public `RepoWikiStore` method, constructed `read_only=True`, issuing no `subprocess`/`gh`/`git` calls — not import the underscore helpers directly.

**Why:** importing private helpers couples callers to internal layout and bypasses the read_only/status-filtering contract the public surface guarantees.
