---
id: 1222
topic: gotchas
source_issue: 10868
source_phase: plan
created_at: 2026-07-31T03:28:15.424901+00:00
status: active
corroborations: 1
---

# Exemption-aware debt reporting in adr_enforcement.py

The ADR enforcement generator must parse `docs/standards/adr_enforcement/exemptions.md` so justified exemptions stop counting as debt.

- `src/arch/generators/adr_enforcement.py` gains an Exempt column and an unexempted-debt headline.
- ADR-0051 (review cadence, no on-disk invariant) shows as exempt, leaving only ADR-0027 in unexempted debt.
- Missing/malformed exemptions file degrades to current output without crashing.

**Why:** An exemption-blind generator re-flags already-justified exemptions as debt, regenerating issues like #10718 and creating false CI failures.
