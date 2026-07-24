---
id: 0158
topic: architecture
source_issue: 10318
source_phase: plan
created_at: 2026-07-24T04:19:41.513768+00:00
status: active
corroborations: 1
---

# Non-`*_loop.py` filenames escape loop auto-discovery on purpose

Name a module without the `_loop.py` suffix (e.g. `src/pr_red_intake.py`) to keep pure logic and collaborator classes out of loop auto-discovery, kill-switch registry, and supervise-list scans, while still importing it from a real `BaseBackgroundLoop` subclass like `PRUnstickerLoop`. Used when retro-consolidating `PrRedRepairLoop`'s classifier fns + `PrRedIntake` collaborator into `PRUnstickerLoop` (#10318) so the standalone loop disappears without losing its logic.

**Why:** prevents an extracted-but-still-`*_loop.py`-named module from being mistaken for a live loop by discovery/completeness architecture tests.
