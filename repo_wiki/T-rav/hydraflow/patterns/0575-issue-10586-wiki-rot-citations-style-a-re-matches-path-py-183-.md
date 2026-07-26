---
id: 0575
topic: patterns
source_issue: 10586
source_phase: plan
created_at: 2026-07-26T02:51:38.701760+00:00
status: active
corroborations: 1
---

# wiki_rot_citations _STYLE_A_RE matches path.py:183 line refs as symbol cites

`_STYLE_A_RE` in `src/wiki_rot_citations.py` is `\b([\w./-]+\.py):(\w+)` — `\w+` also matches digits, so line refs (`base_background_loop.py:141`, `orchestrator.py:948`) get extracted as symbol cites. `verify_cite_ast` can never resolve a numeric symbol, so `WikiRotDetectorLoop` reports these broken forever and escalates after 3 attempts. Measured: 12 distinct broken cites in `docs/wiki/` today, ≥5 are line refs/placeholders; 15 of 23 under the tracked root.

**Why:** any extension of cite extraction or new scan root must exclude numeric-symbol/placeholder candidates first, or it triggers a permanent false-positive escalation storm.
