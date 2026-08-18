---
id: 1471
topic: gotchas
source_issue: 11408
source_phase: plan
created_at: 2026-08-18T02:52:22.040867+00:00
status: active
corroborations: 1
---

# HydraFlowConfig.labels_must_not_be_empty is the sole live-path gate

Rule: `src/config.py:6056` `HydraFlowConfig.labels_must_not_be_empty` is the only guard preventing `StaleIssueLoop` (`src/stale_issue_loop.py:544-575`) from passing empty label sets to `retirement_picks`. Do not add a second caller-side fallback in the loop; the engine-level fail-safe (retire nothing on empty advisory) is the correct defense.

Example: The loop's `advisory_labels` frozenset is config-only with no literal fallback — it relies entirely on the config validator rejecting empty `find_label`/`planner_label`/`diagnose_label`/`parked_label`.

**Why:** A second fallback reintroduces the config-drift the PR removed and masks a relaxed guard.
