---
id: 0382
topic: architecture
source_issue: 11326
source_phase: plan
created_at: 2026-08-16T09:29:42.917644+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Case-fold finder_type but never needle_pattern in class_key

Normalize `finder_type` to a lowercase `[a-z0-9_]` slug and strip both arguments in `generate_class_key`. Do not case-fold `needle_pattern`.

Example: `finder_type.strip().lower()` vs leaving `needle_pattern` unchanged.

**Why:** Regex patterns are case-sensitive; case-folding patterns collides distinct classes and silently buckets unrelated issues under one key.
