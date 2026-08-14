---
id: 1738
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:32.790082+00:00
status: superseded
corroborations: 1
supersedes: 1645
superseded_by: 1834
---

# Scope ledger immutability to merge-base(HEAD, base)

A ledger record present at `merge-base(HEAD, base)` must have zero `--diff-filter=M` commits reachable from HEAD. Records created after the merge-base are exempt — in-PR iteration on a new record is legal because it hasn't merged yet.

Example: Base resolves `origin/staging` → `origin/main` → `HEAD`. The fallback to HEAD makes local runs on a merged branch fully strict.

**Why:** Without merge-base scoping, the check either flags legitimate in-PR drafting or misses post-merge modifications — both break the immutability contract enforced by `scripts/check_console_conformance.py`.
