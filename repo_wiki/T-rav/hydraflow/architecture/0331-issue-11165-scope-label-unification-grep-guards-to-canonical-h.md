---
id: 0331
topic: architecture
source_issue: 11165
source_phase: plan
created_at: 2026-08-14T19:36:20.069077+00:00
status: active
corroborations: 1
---

# Scope label-unification grep guards to canonical-home importers only

Keep CI grep guards for label literals scoped to modules that already import from the canonical home (`trust_fleet_anomaly_detectors`), not all of `src/`.

- Filter with `"trust_fleet_anomaly_detectors" in text` before checking for bare literals.
- Producer loops (staging_bisect, corpus_learning, rc_budget, contract_refresh, principles_audit, memory_backlog, live_corpus_replay, triage_retry, label_drift_watcher, pr_manager, staging_promotion) only write labels — 13 files of blast radius with no extra safety.

**Why:** A fleet-wide guard forces ~13 producer-loop edits and breaks unrelated loop tests without closing any reader/writer divergence gap.
