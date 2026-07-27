---
id: 1150
topic: gotchas
source_issue: 10651
source_phase: plan
created_at: 2026-07-26T15:47:34.663707+00:00
status: active
corroborations: 1
---

# Add sidecar fields with defaults via tolerant from_json_dict — no migration

Extend `SurfacedIssue` in `src/escape/surfaces.py` with new fields that default to falsy values (`attempts: int = 0`, `abandoned_at: str = ""`). Make `from_json_dict` tolerant of missing keys so pre-existing `escape_surfaces.jsonl` files load without error.

- No migration script needed; old rows simply read back with defaults.
- Appenders (`append_attempt`, `append_abandoned`) carry forward prior field values when writing new rows.

**Why:** An append-only JSONL sidecar cannot be migrated in place without rewriting history; tolerant deserialization is the only backward-compatible path.
