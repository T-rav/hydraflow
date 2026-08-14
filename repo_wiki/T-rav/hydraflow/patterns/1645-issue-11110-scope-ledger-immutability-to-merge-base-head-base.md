---
id: 1645
topic: patterns
source_issue: 11110
source_phase: plan
created_at: 2026-08-14T08:05:02.917588+00:00
status: active
corroborations: 1
---

# Scope ledger immutability to merge-base(HEAD, base)

A ledger record present at `merge-base(HEAD, base)` must have zero `--diff-filter=M` commits reachable from HEAD. Records created after the merge-base are exempt — in-PR iteration on a new record is legal because it hasn't merged yet.

Base resolves `origin/staging` → `origin/main` → `HEAD`. The fallback to HEAD makes local runs on a merged branch fully strict.

**Why:** Without merge-base scoping, the check either flags legitimate in-PR drafting or misses post-merge modifications — both break the immutability contract enforced by `scripts/check_console_conformance.py`.
