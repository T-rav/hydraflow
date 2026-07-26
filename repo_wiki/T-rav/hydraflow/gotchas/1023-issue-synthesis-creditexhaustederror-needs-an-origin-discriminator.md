---
id: 1023
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.283770+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# CreditExhaustedError needs an origin discriminator (cli vs prose)

`_pause_for_credits` in `src/orchestrator.py` gated ground-truth CLI signals and scanned transcript prose behind the same probe, so a real weekly-limit cap could be discarded as "quoted prose."

Example: add `CreditExhaustedError.origin` (`CREDIT_ORIGIN_CLI` | `CREDIT_ORIGIN_PROSE`) in `src/subprocess_util.py`, classified via a public `credit_signal_origin(...)` helper. Raise sites tag `cli` for stderr hits, nonzero exit, terminal stream-json error frames, or 402/429 backend responses; a hit found only in scanned agent output is `prose`. Only `prose` origin goes through the `_probe_anthropic` gate.

**Why:** prevents a subscription weekly cap (which `_probe_anthropic` is structurally blind to) from being treated the same as unverifiable transcript text, without reopening #9895/#9807 (transcript prose alone still can't pause).
