---
id: 1437
topic: gotchas
source_issue: 11320
source_phase: plan
created_at: 2026-08-16T08:37:33.480353+00:00
status: active
corroborations: 1
---

# Apply text caps before fencing untrusted regions — never after

In `_build_diagnosis_prompt` (`src/diagnostic_runner.py`), apply size caps (`ci_logs[-8000:]`, `pr_diff[:12000]`, `agent_transcript[:4000]`) **before** wrapping in `<untrusted_*>` tags. Truncating after fencing can slice off a closing delimiter, enabling a forged-close-tag break-out.

- Each attacker-derived region gets a distinct label: `issue_title`, `issue_body`, `ci_logs`, etc.
- Emit `UNTRUSTED_DATA_PREAMBLE` once near the top of each prompt.
- System-generated blocks (e.g. previous-attempts) stay unfenced per ADR-0092.
- Absent field ⇒ no section, never an empty fence.

**Why:** A truncated closing tag lets untrusted content escape the fenced region and reach the model as trusted instruction.
