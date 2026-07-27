---
id: 1176
topic: gotchas
source_issue: 10748
source_phase: plan
created_at: 2026-07-27T22:35:59.585784+00:00
status: active
corroborations: 1
---

# --encoded-as is mandatory for all EscapeLedger resolutions regardless of reason

Always include `--encoded-as` in any resolution command a finding body prescribes, even when the operative flag is `--confidence`.

- `EscapeLedger.append_resolution` requires `--encoded-as`.
- `scripts/resolve_escape.py` CLI validates it.
- A low-confidence body must emit both `--confidence` and `--encoded-as`, not swap one for the other.

**Why:** Dropping `--encoded-as` from a low-confidence prescription causes the resolve command to fail at the operator's terminal, leaving the finding open.
