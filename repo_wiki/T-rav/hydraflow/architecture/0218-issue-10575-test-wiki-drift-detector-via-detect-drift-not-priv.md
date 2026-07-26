---
id: 0218
topic: architecture
source_issue: 10575
source_phase: plan
created_at: 2026-07-26T00:41:55.611451+00:00
status: active
corroborations: 1
---

# Test wiki_drift_detector via detect_drift(), not private loader helpers

Tests exercising `wiki_drift_detector.py` should call the public `detect_drift()` entry point rather than importing `_split_tracked_entry` or `_load_tracked_active_entries` directly. Cross-module `_`-prefixed imports are a documented repo gotcha (see `docs/wiki/gotchas.md`). **Why:** private helpers can be renamed or refactored without notice, silently breaking tests that reach past the public API.
