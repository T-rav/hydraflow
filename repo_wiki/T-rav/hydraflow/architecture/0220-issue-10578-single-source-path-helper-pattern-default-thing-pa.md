---
id: 0220
topic: architecture
source_issue: 10578
source_phase: plan
created_at: 2026-07-26T01:20:17.466834+00:00
status: active
corroborations: 1
---

# Single-source path helper pattern: `default_<thing>_path(config)`

For a resource path computed identically at multiple call sites (e.g. `escape_ledger.jsonl`), centralize it as a module-private filename constant plus a public `default_X_path(config) -> Path` function in the module that owns the resource, returning `config.diagnostics_dir / _FILENAME`. Callers keep their existing property/method but delegate to the helper in one line, so behavior and tests are unchanged. Precedent: `wiki_maint_queue.default_queue_path(config)`; applied to `src/escape/ledger.py`'s `default_ledger_path(config)` replacing duplicated `_LEDGER_FILENAME` logic in `escape_ledger_loop.py`, `sampled_audit_loop.py`, `service_registry.py`, and `vitals/observe.py`.
**Why:** prevents the concept-scatter sensor (issue #10104) from flagging the same on-disk path as independently resolved in 4+ places.
