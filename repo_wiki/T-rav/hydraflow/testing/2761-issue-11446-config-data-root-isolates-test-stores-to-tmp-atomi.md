---
id: 2761
topic: testing
source_issue: 11446
source_phase: plan
created_at: 2026-08-18T09:14:02.932568+00:00
status: active
corroborations: 1
---

# config.data_root isolates test stores to tmp; atomic_write creates parents

Under `ConfigFactory`/`make_bg_loop_deps`, `config.data_root` resolves to `<tmp>/repo/.hydraflow`, so real stores (e.g. `DedupStore`) are tmp-isolated per test with no manual cleanup.

- `atomic_write` creates parent directories, so no pre-`mkdir` of `data_root / "dedup"` is needed.
- A missing dedup file yields an empty set on tick 1 — behaviour is unchanged; only the repeat path moves.
- Guard against `data_root=Path(".")` writing to process CWD (see `test_adr_conformance_scenario.py`).

**Why:** Writing dedup JSON to CWD leaks test artifacts into the repo tree and breaks reproducibility across parallel test runs.
