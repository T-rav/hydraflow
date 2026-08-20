---
id: 1517
topic: gotchas
source_issue: 11469
source_phase: plan
created_at: 2026-08-20T06:54:03.674068+00:00
status: active
corroborations: 1
---

# Fail closed on gateway probe mint 422 with actionable operator guidance

Fail closed with actionable operator instructions when `capture_bodies=True` is requested without proper gateway policy configuration. If minting results in a 422, raise `RuntimeError` in `scripts/gateway_probe.py` explicitly stating `GATEWAY_BODY_CAPTURE_REPOS` must list the probe repo slug with `repo_class=hydraflow`.
**Why:** Silent fallthrough would produce incomplete probe artifacts, misleading the honesty tests into thinking full tap-side capture succeeded.
