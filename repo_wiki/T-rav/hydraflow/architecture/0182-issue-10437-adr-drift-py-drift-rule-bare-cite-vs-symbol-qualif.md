---
id: 0182
topic: architecture
source_issue: 10437
source_phase: plan
created_at: 2026-07-24T10:30:36.222732+00:00
status: active
corroborations: 1
---

# adr_drift.py drift rule: bare cite vs symbol-qualified cite

In `src/adr_drift.py`, an ADR's citation of a file is either bare (no `:Symbol` suffix) or symbol-qualified. Bare citations to a `_SHARED_INFRA_MODULES` member never drift; bare citations to a non-member file drift on any change. Symbol-qualified citations only drift when a changed symbol in the diff matches the cited symbol set — a file-only diff with no symbol evidence never drifts a symbol-qualified citation. This dual rule is what let ADRs 84/93/99 keep drifting on real symbol changes while ADR-0106/0055's bare mentions of `base_background_loop.py` stopped false-positiving.

**Why:** Conflating bare and symbol-qualified citation semantics is what produced the #9176-class systemic false positive in the first place.
