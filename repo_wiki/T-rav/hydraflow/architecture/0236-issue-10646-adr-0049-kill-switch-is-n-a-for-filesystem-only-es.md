---
id: 0236
topic: architecture
source_issue: 10646
source_phase: plan
created_at: 2026-07-26T12:21:36.986364+00:00
status: active
corroborations: 1
---

# ADR-0049 kill-switch is N/A for filesystem-only escape-ledger changes

Changes confined to `escape/ledger.py`, `escape/resolve.py`, and `scripts/resolve_escape.py` operate on append-only JSONL with no Port and no new loop — the ADR-0049 kill-switch does not apply. Only changes that introduce or modify Port/loop lifecycle need kill-switch evaluation.

**Why:** Invoking the kill-switch for a pure filesystem path is cargo-culting; it gates service lifecycle, not local JSONL writes.
