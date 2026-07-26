---
id: 0616
topic: patterns
source_issue: 10614
source_phase: plan
created_at: 2026-07-26T11:22:50.702136+00:00
status: active
corroborations: 1
---

# ConfigReloadLoop is digest-gated; unchanged file means zero log lines

`ConfigReloadLoop` hashes `config.json` and skips apply when the digest is unchanged — zero applied fields, no per-field log lines. On malformed JSON, keep last-good values and alert. Kill switch: `HYDRAFLOW_DISABLE_CONFIG_RELOAD_LOOP=1`. Loop follows ADR-0029 caretaker registration with ADR-0049 `enabled_cb` gate.

**Why:** Logging every field on each 600s poll floods operator dashboards with noise when nothing changed.
