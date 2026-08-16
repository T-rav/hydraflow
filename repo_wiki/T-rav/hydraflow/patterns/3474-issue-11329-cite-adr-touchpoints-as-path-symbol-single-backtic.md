---
id: 3474
topic: patterns
source_issue: 11329
source_phase: plan
created_at: 2026-08-16T09:40:01.182582+00:00
status: superseded
corroborations: 1
superseded_by: 3490
---

# Cite ADR touchpoints as path:Symbol single backtick spans

ADR touchpoint cites must be a single symbol-qualified backtick span, never a bare path or a path+Symbol split.

- Correct: `` `src/reviewer.py:ReviewRunner._build_command` ``
- Rejected: `` `src/reviewer.py` `` + `` `ReviewRunner._build_command` `` (parses as two bare cites)
- Rejected: `` `src/reviewer.py` `` alone (drifts when the multi-concern file is edited)

**Why:** Bare path cites make every future edit to multi-concern files silently drift ADR-0092; the symbol qualifier pins the exact call site.
