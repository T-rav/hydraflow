---
id: 1742
topic: patterns
source_issue: 11118
source_phase: plan
created_at: 2026-08-14T10:22:06.549576+00:00
status: active
corroborations: 1
---

# Prefer JSONL replay over new accumulator for retroactive evidence

To make `prompt-inefficiency` filings self-refuting retroactively, replay `PromptTelemetry.load_inferences()` to derive model/tool mix and `cache_read_input_tokens` totals rather than adding a per-source accumulator counter. A new counter starts at zero and leaves the *next* filings just as unfalsifiable; replay derives evidence from existing history immediately. Pair this with the lifetime-cumulative snapshots `compute_skill_efficiency` already differences for endpoint fields on `SkillEfficiencyRow`.

**Why:** The falsifiability gap (e.g. #11093's 2-call window against an 845-call baseline) exists in already-stored history, not in future counts.
