---
id: 0184
topic: architecture
source_issue: 10441
source_phase: plan
created_at: 2026-07-24T10:43:53.902122+00:00
status: active
corroborations: 1
---

# Distinguish 'dependency pointer' vs 'ownership claim' prose when writing ADR Context sections

ADRs like ADR-0106 (decision lives in `src/event_loop_watchdog.py`) sometimes need to mention an unrelated high-churn base class (`base_background_loop.py`) purely as context ("the watchdog lives here"). Citing it with a `src/` prefix makes the ADR-drift auditor treat it as an ownership touchpoint, triggering false drift on unrelated edits to that base class. Write such mentions without the `src/` prefix to signal "reference only, not owned here."
**Why:** keeps `adr_drift.py`'s source-file tracking limited to genuine touchpoints, preventing noisy rollup issues on shared infrastructure files.
