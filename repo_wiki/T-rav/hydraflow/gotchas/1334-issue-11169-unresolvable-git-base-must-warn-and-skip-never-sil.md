---
id: 1334
topic: gotchas
source_issue: 11169
source_phase: plan
created_at: 2026-08-14T19:43:33.955258+00:00
status: active
corroborations: 1
---

# Unresolvable git base must warn-and-skip, never silently pass

When `scripts/check_console_conformance.py` cannot resolve a merge-base across the fallback chain (`GITHUB_BASE_REF`→`origin/<ref>`→`origin/staging`→`origin/main`), it must write a degradation warning to stderr and skip check #6 — not return success and not fail.

The chain resolves via `git merge-base <cand> HEAD` for each candidate in order.

**Why:** Issue #11110 established that a vacuous green (check silently passing when it did not actually run) is the worst failure mode for immutability gates.
