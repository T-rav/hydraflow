---
id: 0937
topic: gotchas
source_issue: 10558
source_phase: plan
created_at: 2026-07-25T23:16:50.588337+00:00
status: active
corroborations: 1
---

# CreditExhaustedError needs an origin discriminator (cli vs prose)

`_pause_for_credits` in `src/orchestrator.py` gated ground-truth CLI signals and scanned transcript prose behind the same probe, so a real weekly-limit cap could be discarded as "quoted prose." Fix: add `CreditExhaustedError.origin` (`CREDIT_ORIGIN_CLI` | `CREDIT_ORIGIN_PROSE`) in `src/subprocess_util.py`, classified via a public `credit_signal_origin(...)` helper. Raise sites tag `cli` for stderr hits, nonzero exit, terminal stream-json error frames, or 402/429 backend responses; a hit found only in scanned agent output is `prose`. Only `prose` origin goes through the `_probe_anthropic` gate.
**Why:** prevents a subscription weekly cap (which `_probe_anthropic` is structurally blind to) from being treated the same as unverifiable transcript text, without reopening #9895/#9807 (transcript prose alone still can't pause).
