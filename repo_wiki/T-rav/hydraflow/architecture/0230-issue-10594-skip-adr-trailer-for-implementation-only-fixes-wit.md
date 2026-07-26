---
id: 0230
topic: architecture
source_issue: 10594
source_phase: plan
created_at: 2026-07-26T04:15:06.679721+00:00
status: active
corroborations: 1
---

# Skip-ADR trailer for implementation-only fixes with no ADR/wiki citation

When a fix touches a private helper cited by no ADR or wiki entry (e.g. `_collect_defined_symbols` in `src/wiki_rot_citations.py`), commit with a `Skip-ADR:` trailer rather than writing a new ADR — the change is implementation-level, not architectural.

**Why:** keeps ADR-0053 ubiquitous-language/citation drift checks from flagging low-level helper changes that carry no architectural decision.
