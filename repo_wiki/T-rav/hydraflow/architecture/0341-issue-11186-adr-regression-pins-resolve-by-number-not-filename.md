---
id: 0341
topic: architecture
source_issue: 11186
source_phase: plan
created_at: 2026-08-15T00:14:35.607872+00:00
status: active
corroborations: 1
---

# ADR regression pins resolve by number, not filename

Resolve ADRs in regression tests via `ADRIndex` by number. Never hardcode `_ADR_DIR / "ADR-0064.md"` or mirror filesystem state in a list. Replace `parse_adr_file(_ADR_DIR / filename)` with `next((a for a in index.adrs() if a.number == number), None)`. `scan_adr_directory` already calls `parse_adr_file` per file, so index-resolved ADRs keep the real parser — no stubs.

**Why:** Routine ADR renumbering or removal reddens unrelated PRs when tests pin by filename.
