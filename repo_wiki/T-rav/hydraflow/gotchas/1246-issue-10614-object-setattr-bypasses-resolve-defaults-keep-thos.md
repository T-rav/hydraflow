---
id: 1246
topic: gotchas
source_issue: 10614
source_phase: plan
created_at: 2026-07-26T11:22:50.702095+00:00
status: active
corroborations: 1
---

# object.__setattr__ bypasses resolve_defaults — keep those fields boot

Fields mutated via `object.__setattr__` skip `resolve_defaults` in `config.py`, so path/profile/harmonize/docker recompute steps never run and harmonization raises a bare `ValueError`. These fields must remain `editability: "boot"` — never promote to `live`.

**Why:** A `live` promotion on these fields crashes the reload path because derived/computed state they depend on is never reconstructed at runtime.
