---
id: 2632
topic: testing
source_issue: 11215
source_phase: plan
created_at: 2026-08-15T05:13:01.079650+00:00
status: active
corroborations: 1
---

# Caretaker loops: prefer existing tick over a new loop

New periodic reconciliation belongs in the existing `MergeStateWatcherLoop` (ADR-0029/0075, 600s tick, first tick just after boot) rather than a new loop. This avoids a new ADR, kill-switch, and fitness contract.

- Fold new counters into the existing tick result.
- Gate with the existing `enabled_cb("merge_state_watcher")` plus a feature-specific env var in the kill-switch tuple list.
- Keep per-tick resume caps small to avoid tripping the loop watchdog.

**Why:** Spinning a new loop multiplies operational surface (watchdog, kill-switch, boot ordering); the caretaker tick already owns the merge-state domain.
